import json, os, shutil, subprocess, sys
from pathlib import Path
import pytest

from proofkit import hookflow, marker

FIX = Path(__file__).resolve().parent / "fixtures"
TRIGGER = str(Path(__file__).resolve().parents[1] / "scripts" / "proof_trigger.py")
CLAIM = "All done, tests pass."


def _tp(tmp_path, text, name="t.jsonl"):
    f = tmp_path / name
    f.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": text}]}}), encoding="utf-8")
    return str(f)


def _work(tmp_path, fixture):
    w = tmp_path / "work"
    shutil.copytree(FIX / fixture, w)
    return w


def _stop(tmp_path, cwd, text=CLAIM, active=False, sid="s1"):
    return hookflow.decide_stop({"session_id": sid, "transcript_path": _tp(tmp_path, text),
                                 "stop_hook_active": active}, cwd, marker_root=tmp_path / "home")


def test_inline_fail_blocks_with_receipt_and_no_subagent(tmp_path):
    out = _stop(tmp_path, _work(tmp_path, "tests_fail"))
    assert out["decision"] == "block"
    assert "FAIL tests" in out["reason"] and "assert 1 == 2" in out["reason"]
    assert "subagent" not in out["reason"].lower()


def test_inline_pass_allows_stop_with_message(tmp_path):
    out = _stop(tmp_path, _work(tmp_path, "tests_pass"))
    assert "decision" not in out
    assert out["systemMessage"].startswith("Proof: PASS")
    assert marker.last_outcome("s1", CLAIM, root=tmp_path / "home") == "pass"


def test_no_runner_defers_to_subagent_with_claim_key(tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    out = _stop(tmp_path, empty)
    assert out["decision"] == "block"
    assert "--claim-key" in out["reason"] and "--session" in out["reason"]
    assert "--root" in out["reason"] and "verifier" in out["reason"].lower()
    assert marker.pending_entry("s1", root=tmp_path / "home") is not None


def test_pending_reblocks_when_verification_not_run(tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    _stop(tmp_path, empty)
    out = _stop(tmp_path, empty, text="ok, spawning it", active=True)
    assert out["decision"] == "block"
    assert "verification was not run" in out["reason"]


def test_pending_cleared_by_recorded_outcome(tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    _stop(tmp_path, empty)
    key, _ = marker.pending_entry("s1", root=tmp_path / "home")
    marker.record_outcome_by_key("s1", key, "inconclusive", root=tmp_path / "home")
    assert _stop(tmp_path, empty, text="Verifier says INCONCLUSIVE.", active=True) is None


def test_fix_loop_runs_inside_chain_and_terminates(tmp_path):
    w = _work(tmp_path, "tests_fail")
    first = _stop(tmp_path, w)
    assert first["decision"] == "block"
    second = _stop(tmp_path, w, active=True)
    assert "attempt 2 of 3" in second["reason"]
    third = _stop(tmp_path, w, active=True)
    assert "attempt 3 of 3" in third["reason"]
    assert _stop(tmp_path, w, active=True) is None


def test_chain_stops_after_pass(tmp_path):
    w = _work(tmp_path, "tests_pass")
    _stop(tmp_path, w)
    assert _stop(tmp_path, w, text="All set, tests pass again.", active=True) is None


def test_budget_zero_defers(tmp_path, monkeypatch):
    monkeypatch.setenv("PROOF_INLINE_BUDGET", "0")
    out = _stop(tmp_path, _work(tmp_path, "tests_pass"))
    assert out["decision"] == "block" and "--claim-key" in out["reason"]


def test_non_claim_is_silent(tmp_path):
    assert _stop(tmp_path, tmp_path, text="Let me look at the file.") is None


def test_trigger_prints_only_json(tmp_path):
    w = _work(tmp_path, "tests_fail")
    env = dict(os.environ, PROOF_HOME=str(tmp_path / "home"))
    p = subprocess.run([sys.executable, TRIGGER], input=json.dumps(
        {"session_id": "s9", "transcript_path": _tp(tmp_path, CLAIM), "stop_hook_active": False}),
        capture_output=True, text=True, env=env, cwd=str(w))
    assert json.loads(p.stdout)["decision"] == "block"


REWORDED = "Fixed it, all tests pass now."


def test_reworded_reclaim_in_fail_chain_counts_chain_attempts(tmp_path):
    w = _work(tmp_path, "tests_fail")
    assert "attempt 1 of 3" in _stop(tmp_path, w)["reason"]
    out = _stop(tmp_path, w, text=REWORDED, active=True)
    assert out["decision"] == "block"
    assert "attempt 2 of 3" in out["reason"]


def test_gate_never_skips_reworded_reclaim_in_fail_chain(tmp_path, monkeypatch):
    from proofkit import gate
    w = _work(tmp_path, "tests_fail")
    assert _stop(tmp_path, w)["decision"] == "block"
    calls = []
    monkeypatch.setattr(gate, "decide", lambda *a, **k: calls.append(1) or {"decision": "skip"})
    out = _stop(tmp_path, w, text=REWORDED, active=True)
    assert out["decision"] == "block"
    assert "FAIL tests" in out["reason"]
    assert calls == []
    # the same gate stub does skip a fresh, first verification
    assert _stop(tmp_path, w, sid="fresh") is None
    assert calls == [1]
