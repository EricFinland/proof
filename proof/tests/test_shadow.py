"""Shadow-mode zero-impact + additive-enrichment tests (proof side).

These tests must NOT require scikit-learn or proofml. The proofml bridge is
monkeypatched so the proof side is exercised in isolation.

Guarantees proven here:
  1. Shadow OFF (no env, no config): the ledger entry has EXACTLY the original
     keys (no shadow_*/behavior), and verdict + exit code are unchanged.
  2. Bridge returns a dict: the entry gains shadow_proba/shadow_model/
     shadow_source/behavior, and verdict + exit code are still unchanged.
  3. maybe_predict returns None when PROOFML_SHADOW is unset.
"""
import json
from pathlib import Path

from proofkit import verdict as _verdict
from proofkit.strategies.base import Result


_ORIGINAL_KEYS = {"project", "overall", "n_claims", "fails", "suspects", "claims", "ts"}


def _read_ledger(home: Path):
    p = home / "ledger.jsonl"
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


def _patch_one_passing_claim(monkeypatch):
    """Make _execute_claims see exactly one passing 'tests' result."""
    def fake_get(strategy):
        def runner(raw, root=None, command=None, expectation=None, timeout=None):
            return Result("all tests pass", "tests", "pytest -q", "1 passed", "pass")
        return runner

    import proofkit.strategies as strategies
    monkeypatch.setattr(strategies, "get", fake_get)

    # Build claim objects with a .strategy/.raw/.command/.expectation shape.
    class _Claim:
        def __init__(self):
            self.strategy = "tests"
            self.raw = "all tests pass"
            self.command = "pytest -q"
            self.expectation = ""
    return [_Claim()]


def test_shadow_off_entry_has_only_original_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("PROOFML_SHADOW", raising=False)
    monkeypatch.setenv("PROOF_HOME", str(tmp_path))

    claims = _patch_one_passing_claim(monkeypatch)
    code = _verdict._execute_claims(claims, root=str(tmp_path), out_dir=str(tmp_path))

    assert code == 0  # passing verdict -> exit 0, unchanged
    entries = _read_ledger(tmp_path)
    assert len(entries) == 1
    assert set(entries[0].keys()) == _ORIGINAL_KEYS
    assert "shadow_proba" not in entries[0]
    assert "behavior" not in entries[0]


def test_shadow_on_adds_keys_without_changing_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("PROOF_HOME", str(tmp_path))

    # Monkeypatch the bridge so we do not need proofml/sklearn.
    fake = {
        "proba": 0.83,
        "model": "logistic_regression",
        "source": "transcript",
        "behavior": {
            "ran_test_cmd": False,
            "claimed_without_running": True,
            "diff_lines": 12,
            "touched_test_files": False,
            "hedged": False,
            "absolute": True,
        },
    }
    import proofkit.shadow as bridge
    monkeypatch.setattr(bridge, "maybe_predict", lambda *a, **k: fake)

    claims = _patch_one_passing_claim(monkeypatch)
    code = _verdict._execute_claims(
        claims, root=str(tmp_path), out_dir=str(tmp_path), transcript="x"
    )

    assert code == 0  # verdict + exit still unchanged
    entries = _read_ledger(tmp_path)
    assert len(entries) == 1
    e = entries[0]
    # Original keys all still present.
    assert _ORIGINAL_KEYS.issubset(set(e.keys()))
    # Additive shadow keys present and correct.
    assert e["shadow_proba"] == 0.83
    assert e["shadow_model"] == "logistic_regression"
    assert e["shadow_source"] == "transcript"
    assert e["behavior"] == fake["behavior"]


def test_maybe_predict_none_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("PROOFML_SHADOW", raising=False)
    # No .proof.toml in tmp_path -> config disabled too.
    from proofkit.shadow import maybe_predict
    assert maybe_predict("all tests pass", transcript="", root=str(tmp_path)) is None


def test_bridge_failure_never_breaks_verdict(tmp_path, monkeypatch):
    """Even if the bridge raises, the entry stays valid and verdict is unchanged."""
    monkeypatch.setenv("PROOF_HOME", str(tmp_path))

    def boom(*a, **k):
        raise RuntimeError("bridge exploded")

    import proofkit.shadow as bridge
    monkeypatch.setattr(bridge, "maybe_predict", boom)

    claims = _patch_one_passing_claim(monkeypatch)
    code = _verdict._execute_claims(
        claims, root=str(tmp_path), out_dir=str(tmp_path), transcript="x"
    )
    assert code == 0
    entries = _read_ledger(tmp_path)
    assert len(entries) == 1
    assert set(entries[0].keys()) == _ORIGINAL_KEYS
