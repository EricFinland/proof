# proof/tests/test_marker.py
# Migrated for marker v2: attempts/outcomes/should_block policy.
# Old already_verified/mark_verified API removed; coverage intentionally migrated.
import json, os, subprocess, sys
from pathlib import Path
from proofkit.marker import (
    claim_key,
    record_attempt,
    record_outcome,
    attempts,
    last_outcome,
    should_block,
)


def test_claim_key_is_stable():
    assert claim_key("All done, tests pass.") == claim_key("All done, tests pass.")


def test_claim_key_different_messages():
    assert claim_key("tests pass") != claim_key("build is clean")


# --- policy: unseen -> True (verify once) ---
def test_should_block_unseen(tmp_path):
    assert should_block("s1", "All done.", root=tmp_path) is True


# --- policy: after record_attempt, still unknown outcome -> same behavior as
#     attempts>=1 but last==None; since last is not "pass", block if attempts<max ---
def test_record_attempt_increments(tmp_path):
    msg = "All done."
    assert attempts("s1", msg, root=tmp_path) == 0
    record_attempt("s1", msg, root=tmp_path)
    assert attempts("s1", msg, root=tmp_path) == 1
    record_attempt("s1", msg, root=tmp_path)
    assert attempts("s1", msg, root=tmp_path) == 2


def test_last_outcome_none_before_record(tmp_path):
    assert last_outcome("s1", "msg", root=tmp_path) is None


def test_record_outcome_sets_last(tmp_path):
    record_attempt("s1", "msg", root=tmp_path)
    record_outcome("s1", "msg", "pass", root=tmp_path)
    assert last_outcome("s1", "msg", root=tmp_path) == "pass"


# --- policy: last == "pass" -> False (already proven) ---
def test_should_block_after_pass(tmp_path):
    msg = "All done."
    record_attempt("s1", msg, root=tmp_path)
    record_outcome("s1", msg, "pass", root=tmp_path)
    assert should_block("s1", msg, root=tmp_path) is False


# --- policy: last == "inconclusive" -> False (nothing more to check) ---
def test_should_block_after_inconclusive(tmp_path):
    msg = "All done."
    record_attempt("s1", msg, root=tmp_path)
    record_outcome("s1", msg, "inconclusive", root=tmp_path)
    assert should_block("s1", msg, root=tmp_path) is False


# --- policy: last == "fail" and attempts < max_cycles -> True (fix loop) ---
def test_should_block_after_fail_within_max(tmp_path):
    msg = "All done."
    record_attempt("s1", msg, root=tmp_path)
    record_outcome("s1", msg, "fail", root=tmp_path)
    # attempts==1, default max_cycles==3 -> block
    assert should_block("s1", msg, max_cycles=3, root=tmp_path) is True


# --- policy: attempts >= max_cycles -> False (give up, no infinite nagging) ---
def test_should_block_gives_up_at_max(tmp_path):
    msg = "All done."
    for _ in range(3):
        record_attempt("s1", msg, root=tmp_path)
    record_outcome("s1", msg, "fail", root=tmp_path)
    # attempts==3 == max_cycles==3 -> False
    assert should_block("s1", msg, max_cycles=3, root=tmp_path) is False


def test_should_block_gives_up_beyond_max(tmp_path):
    msg = "All done."
    for _ in range(5):
        record_attempt("s1", msg, root=tmp_path)
    record_outcome("s1", msg, "fail", root=tmp_path)
    assert should_block("s1", msg, max_cycles=3, root=tmp_path) is False


# --- old-format migration: old value was list of keys ---
def test_old_format_migration(tmp_path):
    """Old schema stored {session: [key1, key2]} (list). On read must migrate
    each key to {"attempts": 1, "last": null} and behave correctly."""
    from proofkit.marker import _store
    msg = "All done."
    key = claim_key(msg)
    # Write old-format data directly
    store = _store(tmp_path)
    store.write_text(json.dumps({"s1": [key]}))
    # After migration: attempts==1, last==None, so should_block (fail scenario) True
    assert attempts("s1", msg, root=tmp_path) == 1
    assert last_outcome("s1", msg, root=tmp_path) is None
    # With fail last, would block; here last is None -> policy: last not pass/inconclusive
    # and attempts(1) < max_cycles(3) -> True
    assert should_block("s1", msg, max_cycles=3, root=tmp_path) is True


# --- different sessions are isolated ---
def test_different_sessions_isolated(tmp_path):
    msg = "All done."
    record_attempt("s1", msg, root=tmp_path)
    record_outcome("s1", msg, "pass", root=tmp_path)
    # s2 has never seen this message
    assert should_block("s2", msg, root=tmp_path) is True


# --- different claims in same session are isolated ---
def test_different_claims_isolated(tmp_path):
    record_attempt("s1", "claim A", root=tmp_path)
    record_outcome("s1", "claim A", "pass", root=tmp_path)
    assert should_block("s1", "claim B", root=tmp_path) is True


# --- verify --session integration: outcome written after subprocess verify ---
PROOF = str(Path(__file__).resolve().parents[1] / "scripts" / "proof.py")
FIX_FAIL = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tests_fail"


def test_verify_session_records_outcome(tmp_path):
    """verify --session s1 against tests_fail should record last_outcome == fail."""
    msg_text = "All done, tests pass."
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant",
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": msg_text}]},
    }))
    proof_home = tmp_path / "home"
    env = dict(os.environ, PROOF_HOME=str(proof_home))
    r = subprocess.run(
        [sys.executable, PROOF, "verify",
         "--transcript", str(transcript),
         "--root", str(FIX_FAIL),
         "--session", "s1"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert r.returncode == 1  # tests_fail -> FAIL
    lo = last_outcome("s1", msg_text, root=proof_home)
    assert lo == "fail"
