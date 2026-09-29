import os
from pathlib import Path

from proofkit import baseline, changeset, redgreen
from proofkit.strategies.base import Budget

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _setup(repo, tmp_path, code):
    repo.write(".gitignore", "node_modules/\n")
    repo.write("pyproject.toml", "[tool.pytest.ini_options]\npythonpath = [\".\"]\n")
    repo.write("calc.py", code)
    repo.commit()
    return baseline.capture(repo.path, "s", marker_root=tmp_path / "home")


def _run(repo, tmp_path, b, msg="I fixed the bug."):
    cs = changeset.compute(repo.path, b)
    spec = redgreen.find_repro(msg, cs, repo.path, {})
    return spec, redgreen.run(msg, spec, repo.path, b.commit, Budget(None), marker_root=tmp_path / "home")


def _work_empty(tmp_path):
    work = tmp_path / "home" / "work"
    return not work.exists() or not any(work.iterdir())


def test_red_then_green_passes(git_repo, tmp_path):
    b = _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("calc.py", FIXED)
    git_repo.write("tests/test_calc.py", TEST)
    spec, r = _run(git_repo, tmp_path, b)
    assert spec.source == "tests" and r.verdict == "pass", r.raw_output
    assert "fix proven" in r.raw_output


def test_green_on_baseline_is_suspect(git_repo, tmp_path):
    b = _setup(git_repo, tmp_path, FIXED)
    git_repo.write("tests/test_calc.py", TEST)
    _, r = _run(git_repo, tmp_path, b)
    assert r.verdict == "suspect" and r.findings[0].rule == "repro-already-green"


def test_still_failing_is_fail(git_repo, tmp_path):
    b = _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("tests/test_calc.py", TEST)
    _, r = _run(git_repo, tmp_path, b)
    assert r.verdict == "fail"


def test_env_failure_is_inconclusive(git_repo, tmp_path):
    b = _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("calc.py", FIXED)
    spec = redgreen.ReproSpec(["definitely-not-a-command-xyz"], "claim", [])
    r = redgreen.run("I fixed the bug.", spec, git_repo.path, b.commit, Budget(None),
                     marker_root=tmp_path / "home")
    assert r.verdict in ("inconclusive", "fail")
    # current tree also cannot run it, so it must never be "pass"
    assert r.verdict != "pass"


def test_baseline_env_failure_with_green_now_is_inconclusive(git_repo, tmp_path):
    b = _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("calc.py", FIXED)
    git_repo.write("helper_mod.py", "X = 1\n")
    spec = redgreen.ReproSpec(["python", "-c", "import helper_mod"], "claim", [])
    r = redgreen.run("I fixed the bug.", spec, git_repo.path, b.commit, Budget(None),
                     marker_root=tmp_path / "home")
    assert r.verdict == "inconclusive", r.raw_output


def test_repro_sources(git_repo, tmp_path):
    b = _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("calc.py", FIXED)
    cs = changeset.compute(git_repo.path, b)
    assert redgreen.find_repro("I fixed the bug.", cs, git_repo.path, {}) is None
    s = redgreen.find_repro("I fixed the bug.\nRepro: `python -c \"import calc; assert calc.add(2,3)==5\"`",
                            cs, git_repo.path, {})
    assert s.source == "claim" and s.command[0] == "python"
    s2 = redgreen.find_repro("I fixed it.", cs, git_repo.path, {"repro": {"command": "python -m pytest -q"}})
    assert s2.source == "config"


def test_no_spec_is_inconclusive(git_repo, tmp_path):
    b = _setup(git_repo, tmp_path, BUGGY)
    r = redgreen.run("I fixed the bug.", None, git_repo.path, b.commit, Budget(None),
                     marker_root=tmp_path / "home")
    assert r.verdict == "inconclusive" and "no repro found" in r.raw_output
    assert _work_empty(tmp_path)


def test_cleanup_keeps_real_node_modules(git_repo, tmp_path, monkeypatch):
    b = _setup(git_repo, tmp_path, BUGGY)
    (git_repo.path / "node_modules").mkdir()
    (git_repo.path / "node_modules" / "keep.txt").write_text("keep", encoding="utf-8")
    git_repo.write("calc.py", FIXED)
    git_repo.write("tests/test_calc.py", TEST)

    # Spy on link creation so the test proves the junction (Windows) or
    # symlink (elsewhere) path really ran, not a silent fallback.
    made = []
    real_link = redgreen._link_deps

    def spy(root, wt):
        links = real_link(root, wt)
        for link in links:
            assert (Path(link) / "keep.txt").read_text(encoding="utf-8") == "keep"
        made.extend(links)
        return links

    monkeypatch.setattr(redgreen, "_link_deps", spy)
    _, r = _run(git_repo, tmp_path, b)
    assert r.verdict == "pass", r.raw_output
    assert len(made) == 1
    assert not os.path.lexists(made[0])
    assert (git_repo.path / "node_modules" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert git_repo.git("worktree", "list").count("\n") == 1
    assert _work_empty(tmp_path)


def test_failed_unlink_never_deletes_through_link(git_repo, tmp_path, monkeypatch):
    b = _setup(git_repo, tmp_path, BUGGY)
    (git_repo.path / "node_modules").mkdir()
    (git_repo.path / "node_modules" / "keep.txt").write_text("keep", encoding="utf-8")
    git_repo.write("calc.py", FIXED)
    git_repo.write("tests/test_calc.py", TEST)
    made = []
    real_link = redgreen._link_deps

    def spy(root, wt):
        links = real_link(root, wt)
        made.extend(links)
        return links

    monkeypatch.setattr(redgreen, "_link_deps", spy)
    monkeypatch.setattr(redgreen, "_unlink", lambda link: None)  # simulate a failed unlink
    _run(git_repo, tmp_path, b)
    assert len(made) == 1
    assert (git_repo.path / "node_modules" / "keep.txt").read_text(encoding="utf-8") == "keep"
    # The worktree is left in place rather than risking a delete through the link.
    link = Path(made[0])
    assert os.path.lexists(link)
    # Test-side cleanup: remove the link itself first, then the worktree.
    if os.name == "nt":
        os.rmdir(link)
    else:
        os.unlink(link)
    git_repo.git("worktree", "remove", "--force", str(link.parent))
    assert (git_repo.path / "node_modules" / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_copy_never_writes_through_a_link(tmp_path):
    wt = tmp_path / "wt"
    outside = tmp_path / "outside"
    wt.mkdir()
    outside.mkdir()
    assert redgreen._make_link(outside, wt / "lnk")
    assert redgreen._contained(wt, wt / "tests" / "test_x.py")
    assert not redgreen._contained(wt, wt / "lnk" / "test_x.py")
    redgreen._unlink(wt / "lnk")
    assert not os.path.lexists(wt / "lnk") and outside.is_dir()


def test_bad_base_commit_is_inconclusive_and_cleans_up(git_repo, tmp_path):
    b = _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("tests/test_calc.py", TEST)
    cs = changeset.compute(git_repo.path, b)
    spec = redgreen.find_repro("I fixed the bug.", cs, git_repo.path, {})
    r = redgreen.run("I fixed the bug.", spec, git_repo.path, "0" * 40, Budget(None),
                     marker_root=tmp_path / "home")
    assert r.verdict == "inconclusive"
    assert git_repo.git("worktree", "list").count("\n") == 1
    assert _work_empty(tmp_path)


def test_user_index_and_head_untouched(git_repo, tmp_path):
    b = _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("calc.py", FIXED)
    git_repo.write("tests/test_calc.py", TEST)
    cs = changeset.compute(git_repo.path, b)
    spec = redgreen.find_repro("I fixed the bug.", cs, git_repo.path, {})
    index = git_repo.path / ".git" / "index"
    before = (index.read_bytes(), git_repo.git("rev-parse", "HEAD"),
              (git_repo.path / "calc.py").read_text(encoding="utf-8"))
    r = redgreen.run("I fixed the bug.", spec, git_repo.path, b.commit, Budget(None),
                     marker_root=tmp_path / "home")
    assert r.verdict == "pass", r.raw_output
    after = (index.read_bytes(), git_repo.git("rev-parse", "HEAD"),
             (git_repo.path / "calc.py").read_text(encoding="utf-8"))
    assert before == after


def test_low_budget_defers(git_repo, tmp_path):
    b = _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("tests/test_calc.py", TEST)
    cs = changeset.compute(git_repo.path, b)
    spec = redgreen.find_repro("I fixed the bug.", cs, git_repo.path, {})
    r = redgreen.run("I fixed the bug.", spec, git_repo.path, b.commit, Budget(5),
                     marker_root=tmp_path / "home")
    assert r.verdict == "deferred"
