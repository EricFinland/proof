"""Tests for M9: proof check subcommand (verify any claim without a transcript)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROOF = str(ROOT / "scripts" / "proof.py")
FIX_FAIL = ROOT / "tests" / "fixtures" / "tests_fail"
FIX_PASS = ROOT / "tests" / "fixtures" / "tests_pass"


# ---------------------------------------------------------------------------
# M9.1: claim that tests pass against a failing fixture -> exit 1, FAIL stdout
# ---------------------------------------------------------------------------

def test_check_tests_fail(tmp_path):
    env = dict(os.environ, PROOF_HOME=str(tmp_path / "phome"))
    r = subprocess.run(
        [sys.executable, PROOF, "check", "tests pass", "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert r.returncode == 1
    assert "FAIL" in r.stdout
    # proof-report.md must be written in cwd
    assert (tmp_path / "proof-report.md").exists()


# ---------------------------------------------------------------------------
# M9.2: claim that tests pass against a passing fixture -> exit 0, PASS stdout
# ---------------------------------------------------------------------------

def test_check_tests_pass(tmp_path):
    env = dict(os.environ, PROOF_HOME=str(tmp_path / "phome"))
    r = subprocess.run(
        [sys.executable, PROOF, "check", "tests pass", "--root", str(FIX_PASS)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert r.returncode == 0
    assert "PASS" in r.stdout


# ---------------------------------------------------------------------------
# M9.3: unmappable claim text -> exit 2, INCONCLUSIVE + "no checkable claims"
# ---------------------------------------------------------------------------

def test_check_no_claims(tmp_path):
    env = dict(os.environ, PROOF_HOME=str(tmp_path / "phome"))
    r = subprocess.run(
        [sys.executable, PROOF, "check", "looks nice"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert r.returncode == 2
    assert "INCONCLUSIVE" in r.stdout
    assert "no checkable claims" in r.stdout


# ---------------------------------------------------------------------------
# M9.4: check appends to ledger
# ---------------------------------------------------------------------------

def test_check_appends_ledger(tmp_path):
    proof_home = tmp_path / "phome"
    proof_home.mkdir()
    env = dict(os.environ, PROOF_HOME=str(proof_home))
    subprocess.run(
        [sys.executable, PROOF, "check", "tests pass", "--root", str(FIX_FAIL)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    ledger_path = proof_home / "ledger.jsonl"
    assert ledger_path.exists(), "ledger.jsonl not created"
    lines = [l for l in ledger_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["overall"] == "fail"
