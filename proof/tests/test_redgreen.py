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
    _, r = _run(git_repo, tmp_path, b)
    assert len(made) == 1
    assert (git_repo.path / "node_modules" / "keep.txt").read_text(encoding="utf-8") == "keep"
    # The worktree is left in place rather than risking a delete through the link.
    link = Path(made[0])
    assert os.path.lexists(link)
    assert "left in place" in r.raw_output and str(link.parent) in r.raw_output
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


# Ruling R9a: red needs evidence that tests ran and failed.

def test_baseline_collection_error_is_inconclusive(git_repo, tmp_path):
    # add() is already correct at the baseline; the "fix" only adds an unrelated
    # marker() that the new test imports, so the baseline dies at collection.
    b = _setup(git_repo, tmp_path, FIXED)
    git_repo.write("calc.py", FIXED + "\n\ndef marker():\n    return 1\n")
    git_repo.write("tests/test_calc.py",
                   "from calc import add, marker\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    spec, r = _run(git_repo, tmp_path, b)
    assert spec.source == "tests"
    assert r.verdict == "inconclusive", r.raw_output
    assert "pytest exit 2" in r.raw_output


def test_baseline_pytest_usage_error_is_inconclusive(git_repo, tmp_path):
    # The fix adds a plugin that registers --myflag; the baseline pytest rejects it (exit 4).
    b = _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("calc.py", FIXED)
    git_repo.write("myplugin.py", "def pytest_addoption(parser):\n"
                   "    parser.addoption('--myflag', action='store_true')\n")
    git_repo.write("pyproject.toml", "[tool.pytest.ini_options]\npythonpath = [\".\"]\n"
                   "addopts = \"-p myplugin\"\n")
    git_repo.write("tests/test_calc.py", TEST)
    spec = redgreen.ReproSpec(["python", "-m", "pytest", "-q", "--myflag", "tests/test_calc.py"],
                              "tests", ["tests/test_calc.py"])
    r = redgreen.run("I fixed the bug.", spec, git_repo.path, b.commit, Budget(None),
                     marker_root=tmp_path / "home")
    assert r.verdict == "inconclusive", r.raw_output
    assert "pytest exit 4" in r.raw_output


def _judge(cmd, red_code, red_out, source="tests"):
    spec = redgreen.ReproSpec(cmd, source, ["t"])
    green = {"code": 0, "output": "ok", "timed_out": False}
    red = {"code": red_code, "output": red_out, "timed_out": False}
    return redgreen._judge("I fixed it.", spec, " ".join(cmd), red, green).verdict


def test_pytest_red_classification():
    py = ["python", "-m", "pytest", "-q", "tests/test_x.py"]
    assert _judge(py, 1, "FAILED tests/test_x.py::test_a - assert 1 == 2") == "pass"
    for code in (2, 3, 4, 5):
        assert _judge(py, code, "error: unrecognized arguments: --x") == "inconclusive"
    assert _judge(py, 0, "1 passed") == "suspect"


def test_go_red_classification():
    go = ["go", "test", "./calc"]
    assert _judge(go, 1, "--- FAIL: TestAdd (0.00s)\nFAIL\tex/calc") == "pass"
    assert _judge(go, 1, "FAIL\tex/calc [build failed]") == "inconclusive"
    assert _judge(go, 1, "FAIL\tex/calc [setup failed]") == "inconclusive"
    assert _judge(go, 1, "./calc_test.go:9:2: undefined: Marker") == "inconclusive"
    assert _judge(go, 1, "exit status 1") == "inconclusive"


def test_js_red_classification():
    for cmd in (["npm", "test", "--silent", "--", "a.test.js"], ["npx", "vitest", "run", "a.test.ts"],
                ["npx", "jest", "a.test.js"], ["pnpm", "run", "test", "a.test.js"],
                ["yarn", "run", "test", "a.test.js"], ["bun", "run", "test", "a.test.js"]):
        assert _judge(cmd, 1, "expect(received).toBe(expected)\nTests: 1 failed") == "pass"
        for out in ("Test suite failed to run", "Failed to load url ./calc", "Failed to resolve import",
                    "Cannot find module './calc'", "SyntaxError: Unexpected token"):
            assert _judge(cmd, 1, out) == "inconclusive", (cmd, out)


def test_runner_rules_apply_by_argv_whatever_the_source():
    for source in ("config", "claim"):
        assert _judge(["python", "-m", "pytest", "-q"], 2, "Interrupted: 1 error", source) == "inconclusive"
        assert _judge(["python", "-m", "pytest", "-q"], 1, "FAILED t::a", source) == "pass"
        assert _judge(["npx", "jest"], 1, "Cannot find module './calc'", source) == "inconclusive"
        assert _judge(["npx", "vitest", "run"], 1, "SyntaxError: bad", source) == "inconclusive"
        assert _judge(["npm", "test"], 1, "Test suite failed to run", source) == "inconclusive"
        assert _judge(["./node_modules/.bin/jest.cmd"], 1, "expect(1).toBe(2)", source) == "pass"
        assert _judge(["go", "test", "./..."], 1, "exit status 1", source) == "inconclusive"
        assert _judge(["go", "test", "./..."], 1, "--- FAIL: TestA", source) == "pass"


def test_unknown_commands_keep_the_simple_rule():
    for source in ("config", "claim"):
        assert _judge(["./repro.sh"], 2, "boom", source) == "pass"
        assert _judge(["python", "-c", "assert 0"], 1, "AssertionError", source) == "pass"
        assert _judge(["./repro.sh"], 1, "No module named x", source) == "inconclusive"
        assert _judge(["npm", "run", "build"], 1, "SyntaxError", source) == "pass"


def test_config_pytest_repro_collection_error_is_inconclusive(git_repo, tmp_path):
    # A test file the targeted source cannot name (check_*.py), so the configured
    # repro command is used; the baseline dies at collection (pytest exit 2).
    git_repo.write(".gitignore", "node_modules/\n")
    git_repo.write("pyproject.toml", "[tool.pytest.ini_options]\npythonpath = [\".\"]\n"
                   "python_files = [\"check_*.py\"]\n")
    git_repo.write("calc.py", FIXED)
    git_repo.commit()
    b = baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    git_repo.write("calc.py", FIXED + "\n\ndef marker():\n    return 1\n")
    git_repo.write("tests/check_calc.py",
                   "from calc import add, marker\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    cs = changeset.compute(git_repo.path, b)
    spec = redgreen.find_repro("I fixed the bug.", cs, git_repo.path,
                               {"repro": {"command": "python -m pytest -q"}})
    assert spec.source == "config" and spec.copy_files == ["tests/check_calc.py"]
    r = redgreen.run("I fixed the bug.", spec, git_repo.path, b.commit, Budget(None),
                     marker_root=tmp_path / "home")
    assert r.verdict == "inconclusive", r.raw_output
    assert "pytest exit 2" in r.raw_output
    assert _work_empty(tmp_path)


# Ruling R9b: the repro runs in the requested project root.

def _setup_app(repo, tmp_path, code):
    repo.write(".gitignore", "node_modules/\n")
    repo.write("README.md", "top level\n")
    repo.write("app/pyproject.toml", "[tool.pytest.ini_options]\npythonpath = [\".\"]\n")
    repo.write("app/calc.py", code)
    repo.commit()
    return baseline.capture(repo.path, "s", marker_root=tmp_path / "home")


def _run_app(repo, tmp_path, b):
    app = repo.path / "app"
    cs = changeset.compute(repo.path, b)
    spec = redgreen.find_repro("I fixed the bug.", cs, app, {})
    return spec, redgreen.run("I fixed the bug.", spec, app, b.commit, Budget(None),
                              marker_root=tmp_path / "home")


def test_subdir_project_red_then_green_passes(git_repo, tmp_path, monkeypatch):
    b = _setup_app(git_repo, tmp_path, BUGGY)
    (git_repo.path / "app" / "node_modules").mkdir()
    (git_repo.path / "app" / "node_modules" / "keep.txt").write_text("keep", encoding="utf-8")
    git_repo.write("app/calc.py", FIXED)
    git_repo.write("app/tests/test_calc.py", TEST)
    git_repo.write("other/tests/test_other.py", "def test_o():\n    assert False\n")
    made = []
    real_link = redgreen._link_deps

    def spy(project, wt_project):
        links = real_link(project, wt_project)
        made.extend(links)
        return links

    monkeypatch.setattr(redgreen, "_link_deps", spy)
    spec, r = _run_app(git_repo, tmp_path, b)
    assert spec.cwd == "app"
    assert spec.command[-1:] == ["tests/test_calc.py"]  # other/ is outside the project root
    assert r.verdict == "pass", r.raw_output
    assert len(made) == 1 and Path(made[0]).parent.name == "app"
    assert (git_repo.path / "app" / "node_modules" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert git_repo.git("worktree", "list").count("\n") == 1
    assert _work_empty(tmp_path)


def test_subdir_project_noop_fix_fails(git_repo, tmp_path):
    b = _setup_app(git_repo, tmp_path, BUGGY)
    git_repo.write("app/calc.py", BUGGY + "# tidy\n")
    git_repo.write("app/tests/test_calc.py", TEST)
    _, r = _run_app(git_repo, tmp_path, b)
    assert r.verdict == "fail", r.raw_output
    assert _work_empty(tmp_path)


def test_subdir_project_already_green_is_suspect(git_repo, tmp_path):
    b = _setup_app(git_repo, tmp_path, FIXED)
    git_repo.write("app/tests/test_calc.py", TEST)
    _, r = _run_app(git_repo, tmp_path, b)
    assert r.verdict == "suspect", r.raw_output
    assert r.findings[0].file == "app/tests/test_calc.py"


def test_current_tree_env_failure_is_inconclusive_not_fail():
    spec = redgreen.ReproSpec(["npm", "test"], "claim", ["t"])
    red = {"code": 1, "output": "Tests: 1 failed", "timed_out": False}
    for green in ({"code": 127, "output": "command not found: npm", "timed_out": False},
                  {"code": 1, "output": "/usr/bin/python: No module named pytest", "timed_out": False}):
        r = redgreen._judge("I fixed it.", spec, "npm test", red, green)
        assert r.verdict == "inconclusive", r.raw_output
        assert "current tree could not run the repro (environment)" in r.raw_output


def _stale_worktree(repo, tmp_path, name="wt-old"):
    import time
    work = tmp_path / "home" / "work"
    work.mkdir(parents=True, exist_ok=True)
    wt = work / name
    repo.git("worktree", "add", "--detach", str(wt), "HEAD")
    (repo.path / "node_modules").mkdir(exist_ok=True)
    (repo.path / "node_modules" / "keep.txt").write_text("keep", encoding="utf-8")
    (wt / "sub").mkdir(exist_ok=True)
    assert redgreen._make_link(repo.path / "node_modules", wt / "sub" / "node_modules")
    old = time.time() - 7200
    os.utime(wt, (old, old))
    return wt


def test_sweep_removes_stale_worktrees_without_touching_link_targets(git_repo, tmp_path):
    _setup(git_repo, tmp_path, BUGGY)
    wt = _stale_worktree(git_repo, tmp_path)
    fresh = tmp_path / "home" / "work" / "wt-fresh"
    fresh.mkdir()
    other = tmp_path / "home" / "work" / "keepme"
    other.mkdir()
    os.utime(other, (0, 0))
    redgreen._sweep(tmp_path / "home")
    assert not os.path.lexists(wt)
    assert (git_repo.path / "node_modules" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert git_repo.git("worktree", "list").count("\n") == 1
    assert fresh.is_dir() and other.is_dir()


def test_sweep_keeps_stale_worktree_whose_link_cannot_be_removed(git_repo, tmp_path, monkeypatch):
    _setup(git_repo, tmp_path, BUGGY)
    wt = _stale_worktree(git_repo, tmp_path)
    monkeypatch.setattr(redgreen, "_unlink", lambda link: None)
    redgreen._sweep(tmp_path / "home")
    assert wt.is_dir() and os.path.lexists(wt / "sub" / "node_modules")
    assert (git_repo.path / "node_modules" / "keep.txt").read_text(encoding="utf-8") == "keep"
    monkeypatch.undo()
    redgreen._unlink(wt / "sub" / "node_modules")
    git_repo.git("worktree", "remove", "--force", str(wt))


def test_run_sweeps_stale_worktrees_first(git_repo, tmp_path):
    _setup(git_repo, tmp_path, BUGGY)
    wt = _stale_worktree(git_repo, tmp_path)
    redgreen.run("I fixed the bug.", None, git_repo.path, "HEAD", Budget(None),
                 marker_root=tmp_path / "home")
    assert not os.path.lexists(wt)
    assert (git_repo.path / "node_modules" / "keep.txt").read_text(encoding="utf-8") == "keep"
