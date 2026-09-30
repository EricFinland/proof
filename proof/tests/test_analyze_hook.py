import json, os, subprocess, sys
from pathlib import Path
from proofkit import baseline, hookflow, marker

PROOF = str(Path(__file__).resolve().parents[1] / "scripts" / "proof.py")
CLAIM = "All done, tests pass."


def _py_repo(repo):
    repo.write("pyproject.toml", "[tool.pytest.ini_options]\npythonpath = [\".\"]\n")
    repo.write("tests/test_a.py", "def test_a():\n    assert 1 == 1\n\ndef test_b():\n    assert 2 == 2\n")
    repo.commit()


def _tp(tmp_path, text):
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": text}]}}), encoding="utf-8")
    return str(f)


def _stop(tmp_path, cwd, active=False, text=CLAIM):
    return hookflow.decide_stop({"session_id": "s", "transcript_path": _tp(tmp_path, text),
        "stop_hook_active": active}, cwd, marker_root=tmp_path / "home")


def test_suspect_blocks_once_then_tells_user(git_repo, tmp_path):
    _py_repo(git_repo)
    baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    git_repo.write("tests/test_a.py", "import pytest\n\ndef test_a():\n    assert 1 == 1\n\n"
                   "@pytest.mark.skip\ndef test_b():\n    assert 2 == 2\n")
    first = _stop(tmp_path, git_repo.path)
    assert first["decision"] == "block" and "skip-added" in first["reason"]
    second = _stop(tmp_path, git_repo.path, active=True)
    assert "decision" not in second and "skip-added" in second["systemMessage"]
    assert marker.last_outcome("s", CLAIM, root=tmp_path / "home") == "suspect"


def test_clean_change_passes(git_repo, tmp_path):
    _py_repo(git_repo)
    baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    git_repo.write("tests/test_c.py", "def test_c():\n    assert 3 == 3\n")
    assert _stop(tmp_path, git_repo.path)["systemMessage"].startswith("Proof: PASS")


def test_analyzer_error_never_fails(git_repo, tmp_path, monkeypatch):
    _py_repo(git_repo)
    baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    git_repo.write("tests/test_a.py", "import pytest\n@pytest.mark.skip\ndef test_a():\n    assert 1\n")
    from proofkit import tamper
    monkeypatch.setattr(tamper, "analyze", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = _stop(tmp_path, git_repo.path)
    assert out["systemMessage"].startswith("Proof: PASS")


def test_check_since_reports_suspect(git_repo, tmp_path):
    _py_repo(git_repo)
    base = git_repo.git("rev-parse", "HEAD").strip()
    git_repo.write("tests/test_a.py", "def test_a():\n    assert 1 == 1\n")
    env = dict(os.environ, PROOF_HOME=str(tmp_path / "home"))
    p = subprocess.run([sys.executable, PROOF, "check", "all tests pass", "--root", str(git_repo.path),
                        "--since", base, "--json"], capture_output=True, text=True, env=env, cwd=str(tmp_path))
    payload = json.loads(p.stdout)
    assert p.returncode == 3 and payload["overall"] == "suspect"
    assert any(f["rule"] == "test-removed" for r in payload["results"] for f in r["findings"])


def test_subdir_makefile_neutered_is_caught(git_repo, tmp_path):
    from proofkit import changeset, tamper
    git_repo.write("app/Makefile", "test:\n\tpytest\n")
    git_repo.write("other/x.txt", "x\n")
    git_repo.commit()
    baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    git_repo.write("app/Makefile", "test:\n\tpytest || true\n")
    git_repo.write("other/x.txt", "changed\n")
    sub = git_repo.path / "app"
    cs = changeset.for_claim(sub, session="s", marker_root=tmp_path / "home")
    assert cs.paths() == ["app/Makefile"]
    found = tamper.analyze(cs, str(sub), {})
    assert [f.rule for f in found] == ["runner-neutered"]


def test_last_slot_suspect_is_shown_not_blocked(git_repo, tmp_path):
    from proofkit.config import load_config
    from proofkit.strategies.base import Budget
    _py_repo(git_repo)
    home = tmp_path / "home"
    baseline.capture(git_repo.path, "s", marker_root=home)
    git_repo.write("tests/test_a.py", "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    assert 1 == 1\n")
    for _ in range(3):
        marker.chain_bump("s", root=home)
    out = hookflow.verify_inline(CLAIM, "s", _tp(tmp_path, CLAIM), git_repo.path,
                                 load_config(str(git_repo.path)), Budget(60), home, 3)
    assert "decision" not in out and "skip-added" in out["systemMessage"]
    assert marker.last_outcome("s", CLAIM, root=home) == "suspect"


def test_analyzer_orchestration_error_does_not_escape(git_repo, tmp_path, monkeypatch):
    _py_repo(git_repo)
    baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    from proofkit import analyze
    monkeypatch.setattr(analyze, "run_analyzers",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = _stop(tmp_path, git_repo.path)
    assert out["systemMessage"].startswith("Proof: PASS")


def test_suspect_then_explanation_tells_user(git_repo, tmp_path):
    _py_repo(git_repo)
    baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    git_repo.write("tests/test_a.py", "import pytest\n\ndef test_a():\n    assert 1 == 1\n\n"
                   "@pytest.mark.skip\ndef test_b():\n    assert 2 == 2\n")
    first = _stop(tmp_path, git_repo.path)
    assert first["decision"] == "block" and "skip-added" in first["reason"]
    out = _stop(tmp_path, git_repo.path, active=True,
                text="The skip is intentional: test_b hits a flaky external service.")
    assert out is not None and "decision" not in out, out
    assert out["systemMessage"].startswith("Proof: SUSPECT") and "skip-added" in out["systemMessage"]


def test_check_since_branch_uses_merge_base(git_repo, tmp_path):
    _py_repo(git_repo)
    main = git_repo.git("rev-parse", "--abbrev-ref", "HEAD").strip()
    git_repo.git("checkout", "-q", "-b", "feature")
    git_repo.git("checkout", "-q", main)
    git_repo.write("tests/test_new.py", "def test_new():\n    assert 3 == 3\n")
    git_repo.commit("main gains a test")
    git_repo.git("checkout", "-q", "feature")
    env = dict(os.environ, PROOF_HOME=str(tmp_path / "home"))
    p = subprocess.run([sys.executable, PROOF, "check", "all tests pass", "--root", str(git_repo.path),
                        "--since", main, "--json"], capture_output=True, text=True, env=env, cwd=str(tmp_path))
    payload = json.loads(p.stdout)
    rules = [f["rule"] for r in payload["results"] for f in r["findings"]]
    assert "test-file-deleted" not in rules, payload
    assert p.returncode == 0 and payload["overall"] == "pass", payload


def test_check_since_unknown_ref_is_a_note(git_repo, tmp_path):
    from proofkit.verdict import _analyze
    _py_repo(git_repo)
    extra, notes = _analyze("all tests pass", [], str(git_repo.path), {}, None, "no-such-ref")
    assert extra == []
    assert any("could not resolve --since no-such-ref" in n for n in notes), notes
