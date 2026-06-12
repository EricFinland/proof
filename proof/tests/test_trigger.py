# proof/tests/test_trigger.py
# Migrated for trigger v2: should_block + record_attempt, --session in directive,
# receipt injection on re-block after fail, max_cycles give-up.
import json, os, subprocess, sys
from pathlib import Path

TRIGGER = str(Path(__file__).resolve().parents[1] / "scripts" / "proof_trigger.py")


def _run(payload, env_root, cwd=None):
    env = dict(os.environ, PROOF_HOME=str(env_root))
    p = subprocess.run(
        [sys.executable, TRIGGER],
        input=json.dumps(payload),
        capture_output=True, text=True, env=env,
        cwd=str(cwd) if cwd else None,
    )
    return p


def _transcript(tmp_path, text):
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps({
        "type": "assistant",
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": text}]},
    }))
    return str(f)


# 1) fresh claim -> block, reason contains --session
def test_fresh_claim_blocks_with_session(tmp_path):
    tp = _transcript(tmp_path, "All done, tests pass.")
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False},
             tmp_path / "home")
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    assert "--session" in out["reason"]
    assert "verifier" in out["reason"].lower()
    assert "--root" in out["reason"]


# 2) after pass outcome recorded -> same claim -> silent
def test_silent_after_pass(tmp_path):
    from proofkit.marker import record_attempt, record_outcome
    msg = "All done, tests pass."
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    tp = _transcript(tmp_path, msg)
    record_attempt("s1", msg, root=home)
    record_outcome("s1", msg, "pass", root=home)
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False}, home)
    assert r.stdout.strip() == ""


# 3) fail outcome -> same claim -> blocks again with receipts when proof-report.md present
def test_reblock_after_fail_with_receipts(tmp_path):
    from proofkit.marker import record_attempt, record_outcome
    msg = "All done, tests pass."
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    cwd = tmp_path / "work"
    cwd.mkdir(parents=True, exist_ok=True)
    tp = _transcript(tmp_path, msg)
    # simulate 1 prior attempt + fail outcome
    record_attempt("s1", msg, root=home)
    record_outcome("s1", msg, "fail", root=home)
    # place a proof-report.md in the cwd
    (cwd / "proof-report.md").write_text("# Proof Report -- FAIL\nsome failure detail")
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False},
             home, cwd=cwd)
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    reason = out["reason"]
    assert "PREVIOUS RECEIPTS" in reason
    assert "attempt 2 of 3" in reason.lower()


# 4) 3 attempts + fail -> silent (gave up)
def test_silent_after_max_cycles(tmp_path):
    from proofkit.marker import record_attempt, record_outcome
    msg = "All done, tests pass."
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    tp = _transcript(tmp_path, msg)
    for _ in range(3):
        record_attempt("s1", msg, root=home)
    record_outcome("s1", msg, "fail", root=home)
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False}, home)
    assert r.stdout.strip() == ""


# 5) stop_hook_active True -> silent (unchanged)
def test_noop_when_stop_hook_active(tmp_path):
    tp = _transcript(tmp_path, "All done, tests pass.")
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": True},
             tmp_path / "home")
    assert r.stdout.strip() == ""


# 6) non-claim -> silent (unchanged)
def test_noop_on_non_claim(tmp_path):
    tp = _transcript(tmp_path, "Let me investigate the failure.")
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False},
             tmp_path / "home")
    assert r.stdout.strip() == ""


# crash-safety: missing transcript_path -> silent exit 0
def test_missing_transcript_path_is_silent(tmp_path):
    r = _run({"session_id": "s1", "stop_hook_active": False}, tmp_path / "home")
    assert r.returncode == 0
    assert r.stdout.strip() == ""


# crash-safety: transcript_path pointing to a directory -> silent exit 0
def test_transcript_path_is_directory_is_silent(tmp_path):
    r = _run({"session_id": "s1", "transcript_path": str(tmp_path), "stop_hook_active": False},
             tmp_path / "home")
    assert r.returncode == 0
    assert r.stdout.strip() == ""
