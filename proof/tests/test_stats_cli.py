"""Tests for M8.2: ledger wiring into run_verify + 'proof stats' subcommand."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROOF = str(ROOT / "scripts" / "proof.py")
FIX_FAIL = ROOT / "tests" / "fixtures" / "tests_fail"


# ---------------------------------------------------------------------------
# 8.2a: empty ledger -> human-readable degraded output
# ---------------------------------------------------------------------------

def test_stats_empty_ledger(tmp_path):
    env = dict(os.environ, PROOF_HOME=str(tmp_path))
    r = subprocess.run(
        [sys.executable, PROOF, "stats"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0
    assert "No verifications recorded yet" in r.stdout


# ---------------------------------------------------------------------------
# 8.2b: run_verify appends to ledger; stats then reports it
# ---------------------------------------------------------------------------

def test_run_verify_appends_ledger_entry(tmp_path):
    """After run_verify against failing fixture, one ledger entry is written."""
    from proofkit.verdict import run_verify
    from proofkit import ledger

    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "All done, tests pass."}]}}))

    proof_home = tmp_path / "proof_home"
    old_env = os.environ.get("PROOF_HOME")
    os.environ["PROOF_HOME"] = str(proof_home)
    try:
        run_verify(transcript=str(t), root=str(FIX_FAIL), out_dir=str(tmp_path))
    finally:
        if old_env is None:
            os.environ.pop("PROOF_HOME", None)
        else:
            os.environ["PROOF_HOME"] = old_env

    entries = ledger.read_entries(root=str(proof_home))
    assert len(entries) == 1
    assert entries[0]["overall"] == "fail"


# ---------------------------------------------------------------------------
# 8.2c: integration -- verify then stats via subprocess with PROOF_HOME
# ---------------------------------------------------------------------------

def test_stats_after_verify_shows_one_lie(tmp_path):
    proof_home = tmp_path / "phome"
    proof_home.mkdir()
    env = dict(os.environ, PROOF_HOME=str(proof_home))

    # Build transcript claiming tests pass
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "All done, tests pass."}]}}))

    # Run verify against tests_fail fixture
    subprocess.run(
        [sys.executable, PROOF, "verify", "--transcript", str(t), "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )

    # stats should show 1 lie caught
    r = subprocess.run(
        [sys.executable, PROOF, "stats"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0
    out = r.stdout
    assert "1" in out          # some mention of 1 lie
    assert "0%" in out or "honesty" in out.lower() or "lie" in out.lower()


def test_stats_after_verify_zero_percent(tmp_path):
    """Honesty rate 0% when only lies recorded."""
    proof_home = tmp_path / "phome"
    proof_home.mkdir()
    env = dict(os.environ, PROOF_HOME=str(proof_home))

    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "All done, tests pass."}]}}))

    subprocess.run(
        [sys.executable, PROOF, "verify", "--transcript", str(t), "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )

    r = subprocess.run(
        [sys.executable, PROOF, "stats"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0
    assert "0%" in r.stdout


# ---------------------------------------------------------------------------
# 8.2d: --json flag parses and has expected keys
# ---------------------------------------------------------------------------

def test_stats_json_flag_empty(tmp_path):
    env = dict(os.environ, PROOF_HOME=str(tmp_path))
    r = subprocess.run(
        [sys.executable, PROOF, "stats", "--json"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)
    for key in ("total", "passes", "fails", "inconclusive", "honesty_rate",
                "clean_streak", "worst_method", "last_catch"):
        assert key in data, f"missing key: {key}"


def test_stats_json_after_verify(tmp_path):
    proof_home = tmp_path / "phome"
    proof_home.mkdir()
    env = dict(os.environ, PROOF_HOME=str(proof_home))

    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "All done, tests pass."}]}}))

    subprocess.run(
        [sys.executable, PROOF, "verify", "--transcript", str(t), "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )

    r = subprocess.run(
        [sys.executable, PROOF, "stats", "--json"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["total"] == 1
    assert data["fails"] == 1
    assert data["passes"] == 0
    assert data["honesty_rate"] == 0.0


# ---------------------------------------------------------------------------
# 8.2e: --days flag filters old entries
# ---------------------------------------------------------------------------

def test_stats_days_filter(tmp_path):
    from proofkit import ledger

    proof_home = tmp_path / "phome"
    now = time.time()
    # Write one old entry and one recent entry
    ledger.append_entry({"overall": "fail", "ts": now - 20 * 86400, "fails": ["tests"],
                          "claims": ["old claim"]}, root=str(proof_home))
    ledger.append_entry({"overall": "pass", "ts": now - 1 * 86400, "fails": [],
                          "claims": ["recent claim"]}, root=str(proof_home))

    env = dict(os.environ, PROOF_HOME=str(proof_home))
    r = subprocess.run(
        [sys.executable, PROOF, "stats", "--days", "7"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0
    # Only 1 entry in last 7 days (the pass), so "1 verified" and honesty 100%
    assert "1" in r.stdout


# ---------------------------------------------------------------------------
# 8.2f: ledger failure does not affect run_verify exit code
# ---------------------------------------------------------------------------

def test_ledger_failure_does_not_affect_exit_code(tmp_path, monkeypatch):
    """If ledger.append_entry raises, run_verify still returns correct exit code."""
    from proofkit.verdict import run_verify
    import proofkit.verdict as verdict_mod

    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "All done, tests pass."}]}}))

    # Patch ledger to raise inside run_verify
    import proofkit.ledger as real_ledger

    def boom(*a, **kw):
        raise RuntimeError("ledger exploded")

    monkeypatch.setattr(real_ledger, "append_entry", boom)

    fix = Path(__file__).resolve().parent / "fixtures" / "tests_fail"
    code = run_verify(transcript=str(t), root=str(fix), out_dir=str(tmp_path))
    # Should still return 1 (FAIL) even though ledger raised
    assert code == 1
