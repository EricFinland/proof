import json

from proofkit import baseline, hookflow

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
FIX = "I fixed the bug in add."


def _setup(repo, tmp_path, code, capture=True):
    repo.write(".gitignore", "node_modules/\n")
    repo.write("pyproject.toml", "[tool.pytest.ini_options]\npythonpath = [\".\"]\n")
    repo.write("calc.py", code)
    repo.commit()
    if capture:
        baseline.capture(repo.path, "s", marker_root=tmp_path / "home")


def _tp(tmp_path, text):
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": text}]}}), encoding="utf-8")
    return str(f)


def _stop(tmp_path, cwd, text=FIX):
    return hookflow.decide_stop({"session_id": "s", "transcript_path": _tp(tmp_path, text),
        "stop_hook_active": False}, cwd, marker_root=tmp_path / "home")


def test_fix_claim_gets_redgreen_receipt(git_repo, tmp_path):
    _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("calc.py", FIXED)
    git_repo.write("tests/test_calc.py", TEST)
    out = _stop(tmp_path, git_repo.path)
    assert out["systemMessage"].startswith("Proof: PASS"), out
    assert "redgreen" in out["systemMessage"]


def test_repro_green_on_baseline_blocks(git_repo, tmp_path):
    _setup(git_repo, tmp_path, FIXED)
    git_repo.write("tests/test_calc.py", TEST)
    out = _stop(tmp_path, git_repo.path)
    assert out["decision"] == "block" and "repro-already-green" in out["reason"], out


def test_approximate_baseline_skips_redgreen(git_repo, tmp_path):
    _setup(git_repo, tmp_path, BUGGY, capture=False)
    git_repo.write("calc.py", FIXED)
    git_repo.write("tests/test_calc.py", TEST)
    out = _stop(tmp_path, git_repo.path, text=FIX + " All tests pass.")
    assert out["systemMessage"].startswith("Proof: PASS"), out
    assert "tests" in out["systemMessage"] and "redgreen" not in out["systemMessage"]


def test_fix_claim_without_repro_gets_hint(git_repo, tmp_path):
    _setup(git_repo, tmp_path, BUGGY)
    git_repo.write("calc.py", FIXED)
    out = _stop(tmp_path, git_repo.path)
    assert out["decision"] == "block", out
    assert "Repro:" in out["reason"] and "no repro found" in out["reason"]
