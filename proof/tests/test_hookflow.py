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
    # the cap ends the loop, but the user is told the claim still fails
    final = _stop(tmp_path, w, active=True)
    assert final is not None and "decision" not in final, final
    assert final["systemMessage"].startswith("Proof: FAIL")
    assert "FAIL tests" in final["systemMessage"] and "assert 1 == 2" in final["systemMessage"]


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


TURN1 = "Done, the tests pass."


def test_abandoned_pending_does_not_disable_next_turn_fix_loop(tmp_path):
    home = tmp_path / "home"
    empty = tmp_path / "empty"; empty.mkdir()
    # turn 1: a deferred claim whose verifier is never run, re-blocked until the cap
    assert _stop(tmp_path, empty, text=TURN1)["decision"] == "block"
    for _ in range(4):
        _stop(tmp_path, empty, text="ok, spawning it", active=True)
    # turn 2: a fresh claim on a failing tree
    w = _work(tmp_path, "tests_fail")
    first = _stop(tmp_path, w)
    assert first["decision"] == "block" and "FAIL tests" in first["reason"], first
    assert "verification was not run" not in first["reason"]
    second = _stop(tmp_path, w, active=True)
    assert second is not None and second.get("decision") == "block", second
    assert "attempt 2 of 3" in second["reason"] and "FAIL tests" in second["reason"]
    assert marker.pending_entry("s1", root=home) is None


def test_fresh_turn_does_not_reblock_old_pending_claim(tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    assert _stop(tmp_path, empty, text=TURN1)["decision"] == "block"
    w = _work(tmp_path, "tests_fail")
    assert "FAIL tests" in _stop(tmp_path, w)["reason"]
    out = _stop(tmp_path, w, active=True)
    assert "verification was not run" not in out["reason"]
    assert "attempt 2 of 3" in out["reason"]


def test_exhausted_pending_in_fail_chain_falls_through_to_reverify(tmp_path):
    home = tmp_path / "home"
    w = _work(tmp_path, "tests_fail")
    assert "FAIL tests" in _stop(tmp_path, w)["reason"]
    marker.set_pending("s1", "Other claim, tests pass.", ["tests"], root=home)
    for _ in range(3):
        marker.record_attempt("s1", "Other claim, tests pass.", root=home)
    out = _stop(tmp_path, w, active=True)
    assert out["decision"] == "block" and "FAIL tests" in out["reason"], out
    assert marker.pending_entry("s1", root=home) is None


def test_giving_up_in_fail_chain_tells_user(tmp_path):
    w = _work(tmp_path, "tests_fail")
    assert "FAIL tests" in _stop(tmp_path, w)["reason"]
    out = _stop(tmp_path, w, text="I could not get this one working.", active=True)
    assert out is not None and "decision" not in out, out
    assert out["systemMessage"].startswith("Proof: FAIL") and "assert 1 == 2" in out["systemMessage"]


def test_pending_cap_tells_user_claim_was_never_verified(tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    assert _stop(tmp_path, empty)["decision"] == "block"
    outs = [_stop(tmp_path, empty, text="ok, spawning it", active=True) for _ in range(3)]
    assert all(o and o.get("decision") == "block" for o in outs[:2]), outs
    final = outs[2]
    assert final is not None and "decision" not in final, final
    assert final["systemMessage"].startswith("Proof: INCONCLUSIVE")
    assert "never verified" in final["systemMessage"]


def test_repeated_claim_is_reverified_after_the_tree_changes(git_repo, tmp_path):
    home = tmp_path / "home"
    git_repo.write(".gitignore", "__pycache__/\n.pytest_cache/\nproof-report.md\n")
    git_repo.write("pyproject.toml", "[tool.pytest.ini_options]\n")
    git_repo.write("test_ok.py", "def test_ok():\n    assert 1 == 1\n")
    git_repo.commit()
    first = _stop(tmp_path, git_repo.path)
    assert first["systemMessage"].startswith("Proof: PASS"), first
    # the same words on an unchanged tree are not re-run
    assert _stop(tmp_path, git_repo.path) is None
    git_repo.write("test_ok.py", "def test_ok():\n    assert 1 == 2\n")
    out = _stop(tmp_path, git_repo.path)
    assert out is not None and out.get("decision") == "block", out
    assert "FAIL tests" in out["reason"]


def test_repeated_claim_outside_git_keeps_prior_pass(tmp_path):
    w = _work(tmp_path, "tests_pass")
    assert _stop(tmp_path, w)["systemMessage"].startswith("Proof: PASS")
    (w / "test_ok.py").write_text("def test_ok():\n    assert 1 == 2\n", encoding="utf-8")
    assert _stop(tmp_path, w) is None


def test_pending_reblock_counts_attempts_on_the_long_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("PROOF_INLINE_BUDGET", "0")
    home = tmp_path / "home"
    long_claim = ("Here is a long summary of the work. " * 170) + "All 250 tests pass."
    w = _work(tmp_path, "tests_pass")
    assert _stop(tmp_path, w, text=long_claim)["decision"] == "block"
    out = _stop(tmp_path, w, text="ok, spawning it", active=True)
    assert "verification was not run" in out["reason"]
    assert marker.attempts("s1", long_claim, root=home) == 2
    key, entry = marker.pending_entry("s1", root=home)
    assert key == marker.claim_key(long_claim) and entry["claim"] == long_claim
