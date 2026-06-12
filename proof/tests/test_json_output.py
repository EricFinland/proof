"""Tests for M12.1: --json output and --version flag."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROOF = str(ROOT / "scripts" / "proof.py")
FIX_FAIL = ROOT / "tests" / "fixtures" / "tests_fail"
FIX_PASS = ROOT / "tests" / "fixtures" / "tests_pass"


def _env(tmp_path):
    return dict(os.environ, PROOF_HOME=str(tmp_path / "phome"))


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------

def test_version_flag(tmp_path):
    r = subprocess.run(
        [sys.executable, PROOF, "--version"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "proof 2.0.0" in r.stdout or "proof 2.0.0" in r.stderr


# ---------------------------------------------------------------------------
# verify --json with failing fixture
# ---------------------------------------------------------------------------

def _build_transcript(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "All done, tests pass."}]}}))
    return str(t)


def test_verify_json_parses(tmp_path):
    t = _build_transcript(tmp_path)
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "verify", "--json",
         "--transcript", t, "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    data = json.loads(r.stdout)
    assert isinstance(data, dict)


def test_verify_json_overall_fail(tmp_path):
    t = _build_transcript(tmp_path)
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "verify", "--json",
         "--transcript", t, "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    data = json.loads(r.stdout)
    assert data["overall"] == "fail"


def test_verify_json_exit_field_is_1(tmp_path):
    t = _build_transcript(tmp_path)
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "verify", "--json",
         "--transcript", t, "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    data = json.loads(r.stdout)
    assert data["exit"] == 1


def test_verify_json_process_returncode_1(tmp_path):
    t = _build_transcript(tmp_path)
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "verify", "--json",
         "--transcript", t, "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert r.returncode == 1


def test_verify_json_no_ascii_fail_lines(tmp_path):
    """JSON mode: stdout must be pure JSON -- no 'FAIL ' ASCII verdict lines."""
    t = _build_transcript(tmp_path)
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "verify", "--json",
         "--transcript", t, "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    # The whole stdout must be one JSON object -- no "FAIL " lines
    assert "FAIL " not in r.stdout
    # Parses cleanly as JSON
    data = json.loads(r.stdout)
    assert "overall" in data


def test_verify_json_results_list(tmp_path):
    t = _build_transcript(tmp_path)
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "verify", "--json",
         "--transcript", t, "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    data = json.loads(r.stdout)
    assert "results" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) >= 1
    for item in data["results"]:
        for key in ("claim", "method", "command", "raw_output", "verdict", "confidence"):
            assert key in item, f"missing key: {key}"


def test_verify_json_report_field(tmp_path):
    t = _build_transcript(tmp_path)
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "verify", "--json",
         "--transcript", t, "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    data = json.loads(r.stdout)
    assert "report" in data
    assert data["report"]  # non-empty string


def test_verify_json_raw_output_truncated(tmp_path):
    """raw_output must not exceed 2000 chars per result."""
    t = _build_transcript(tmp_path)
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "verify", "--json",
         "--transcript", t, "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    data = json.loads(r.stdout)
    for item in data["results"]:
        assert len(item["raw_output"]) <= 2000


# ---------------------------------------------------------------------------
# check --json
# ---------------------------------------------------------------------------

def test_check_json_parses(tmp_path):
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "check", "--json", "tests pass",
         "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    data = json.loads(r.stdout)
    assert isinstance(data, dict)


def test_check_json_same_shape(tmp_path):
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "check", "--json", "tests pass",
         "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    data = json.loads(r.stdout)
    for key in ("overall", "exit", "results", "report"):
        assert key in data, f"missing key: {key}"
    assert data["overall"] == "fail"
    assert data["exit"] == 1
    assert r.returncode == 1


def test_check_json_no_ascii_verdict_lines(tmp_path):
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "check", "--json", "tests pass",
         "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert "FAIL " not in r.stdout
    json.loads(r.stdout)  # must parse cleanly


def test_check_json_inconclusive_unmappable(tmp_path):
    """Unmappable text -> inconclusive, exit 2, returncode 2."""
    env = _env(tmp_path)
    r = subprocess.run(
        [sys.executable, PROOF, "check", "--json", "looks nice"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    data = json.loads(r.stdout)
    assert data["overall"] == "inconclusive"
    assert data["exit"] == 2
    assert r.returncode == 2
