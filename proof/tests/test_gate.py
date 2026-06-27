"""Cost-gate tests (proof side).

These prove the safety invariants of the cost gate WITHOUT requiring proofml or
scikit-learn: the predictor (proofkit.shadow.predict_now) is monkeypatched, so
proofml is never imported.

Guarantees proven here:
  1. Gate OFF (no env, no config): proof_trigger blocks exactly as today; no
     gate.jsonl is written.
  2. Gate ON + proba below threshold + audit_rate 0 -> decision "skip"; the hook
     returns WITHOUT printing a block; gate.jsonl has a skip line.
  3. Gate ON + proba above threshold -> hook blocks; decision "verify" logged.
  4. Gate ON + audit_rate 1.0 + low proba -> decision "audit"; hook still blocks.
  5. Predictor raises / returns None -> FAIL-SAFE: hook blocks.
  6. prior_outcome == "fail" -> never skip even with low proba (re-verify).

proof_trigger.main() is driven in-process by feeding JSON on stdin (monkeypatched
sys.stdin), with a transcript file containing an assistant completion claim.
PROOF_HOME points at a tmp dir so all markers + gate.jsonl land there.
"""
import io
import json
from pathlib import Path

import pytest

import proof_trigger
from proofkit import gate as gate_mod
from proofkit import shadow as shadow_mod
from proofkit.marker import record_attempt, record_outcome


CLAIM = "All done, tests pass."


def _transcript(tmp_path: Path, text: str = CLAIM) -> str:
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps({
        "type": "assistant",
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": text}]},
    }))
    return str(f)


def _run_main(monkeypatch, capsys, tmp_path, home: Path, *, cwd: Path = None):
    """Drive proof_trigger.main() with a fresh-claim payload. Returns stdout str."""
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PROOF_HOME", str(home))
    tp = _transcript(tmp_path)
    payload = {"session_id": "s1", "transcript_path": tp, "stop_hook_active": False}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    work = cwd or tmp_path
    monkeypatch.chdir(work)
    proof_trigger.main()
    return capsys.readouterr().out


def _gate_lines(home: Path):
    p = home / "gate.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# 1) Gate OFF -> blocks exactly as today; no gate.jsonl written.
def test_gate_off_blocks_and_no_log(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("PROOFML_GATE", raising=False)
    home = tmp_path / "home"
    out = _run_main(monkeypatch, capsys, tmp_path, home)
    obj = json.loads(out)
    assert obj["decision"] == "block"
    assert not (home / "gate.jsonl").exists()


# 2) Gate ON + low proba + audit_rate 0 -> skip; no block printed; skip logged.
def test_gate_on_skip(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("PROOFML_GATE", "1")
    monkeypatch.setenv("PROOFML_GATE_THRESHOLD", "0.5")
    monkeypatch.setenv("PROOFML_GATE_AUDIT_RATE", "0")
    monkeypatch.setattr(
        shadow_mod, "predict_now",
        lambda *a, **k: {"proba": 0.02, "model": "m", "source": "transcript",
                         "behavior": {"ran_test_cmd": True}},
    )
    home = tmp_path / "home"
    out = _run_main(monkeypatch, capsys, tmp_path, home)
    assert out.strip() == ""  # no block directive printed
    lines = _gate_lines(home)
    assert len(lines) == 1
    assert lines[0]["decision"] == "skip"
    assert lines[0]["proba"] == 0.02


# 3) Gate ON + high proba -> verify; hook blocks; verify logged.
def test_gate_on_verify_blocks(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("PROOFML_GATE", "1")
    monkeypatch.setenv("PROOFML_GATE_THRESHOLD", "0.5")
    monkeypatch.setenv("PROOFML_GATE_AUDIT_RATE", "0")
    monkeypatch.setattr(
        shadow_mod, "predict_now",
        lambda *a, **k: {"proba": 0.9, "model": "m", "source": "transcript",
                         "behavior": None},
    )
    home = tmp_path / "home"
    out = _run_main(monkeypatch, capsys, tmp_path, home)
    obj = json.loads(out)
    assert obj["decision"] == "block"
    lines = _gate_lines(home)
    assert len(lines) == 1
    assert lines[0]["decision"] == "verify"


# 4) Gate ON + audit_rate 1.0 + low proba -> audit; hook still blocks.
def test_gate_on_audit_blocks(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("PROOFML_GATE", "1")
    monkeypatch.setenv("PROOFML_GATE_THRESHOLD", "0.5")
    monkeypatch.setenv("PROOFML_GATE_AUDIT_RATE", "1.0")
    monkeypatch.setattr(
        shadow_mod, "predict_now",
        lambda *a, **k: {"proba": 0.01, "model": "m", "source": "claim_only",
                         "behavior": None},
    )
    home = tmp_path / "home"
    out = _run_main(monkeypatch, capsys, tmp_path, home)
    obj = json.loads(out)
    assert obj["decision"] == "block"
    lines = _gate_lines(home)
    assert len(lines) == 1
    assert lines[0]["decision"] == "audit"


# 5a) Predictor returns None -> FAIL-SAFE: hook blocks, verify logged w/ reason.
def test_gate_predict_none_failsafe_blocks(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("PROOFML_GATE", "1")
    monkeypatch.setattr(shadow_mod, "predict_now", lambda *a, **k: None)
    home = tmp_path / "home"
    out = _run_main(monkeypatch, capsys, tmp_path, home)
    obj = json.loads(out)
    assert obj["decision"] == "block"
    lines = _gate_lines(home)
    assert len(lines) == 1
    assert lines[0]["decision"] == "verify"
    assert lines[0]["reason"] == "predict_failed"


# 5b) Predictor raises -> FAIL-SAFE: hook still blocks (decide swallows + verifies).
def test_gate_predict_raises_failsafe_blocks(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("PROOFML_GATE", "1")

    def boom(*a, **k):
        raise RuntimeError("predictor exploded")

    monkeypatch.setattr(shadow_mod, "predict_now", boom)
    home = tmp_path / "home"
    out = _run_main(monkeypatch, capsys, tmp_path, home)
    obj = json.loads(out)
    assert obj["decision"] == "block"
    # decide() catches the predictor error and logs a verify decision.
    lines = _gate_lines(home)
    assert len(lines) == 1
    assert lines[0]["decision"] == "verify"


# 6) prior_outcome == "fail" -> never skip even with low proba (re-verify path).
def test_gate_never_skips_after_prior_fail(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("PROOFML_GATE", "1")
    monkeypatch.setenv("PROOFML_GATE_THRESHOLD", "0.5")
    monkeypatch.setenv("PROOFML_GATE_AUDIT_RATE", "0")
    # If the gate were ever consulted it would say skip; it must NOT be.
    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return {"proba": 0.0, "model": "m", "source": "transcript", "behavior": None}

    monkeypatch.setattr(shadow_mod, "predict_now", spy)

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    # Simulate one prior attempt that FAILED for this (session, claim).
    record_attempt("s1", CLAIM, root=home)
    record_outcome("s1", CLAIM, "fail", root=home)

    out = _run_main(monkeypatch, capsys, tmp_path, home)
    obj = json.loads(out)
    assert obj["decision"] == "block"  # re-verify, not skipped
    assert called["n"] == 0  # gate predictor never even consulted
    assert not (home / "gate.jsonl").exists()


# decide() returns None (and does not import proofml) when gating is disabled.
def test_decide_disabled_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("PROOFML_GATE", raising=False)
    # No .proof.toml in tmp_path -> config disabled too.
    result = gate_mod.decide(CLAIM, transcript="", root=str(tmp_path),
                             session="s1", marker_root=str(tmp_path))
    assert result is None
    assert not (Path(tmp_path) / "gate.jsonl").exists()
