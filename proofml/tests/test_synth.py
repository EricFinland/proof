"""Tests for proofml.synth: balance, determinism, learnable separation, fallback."""
from __future__ import annotations

import json

import pytest

from proofml import synth
from proofml.data import load_examples
from proofml.features import labels, to_matrix
from proofml.schema import Example


def test_generate_is_balanced():
    rows = synth.generate(pairs=50, seed=0)
    assert len(rows) == 100
    n_dec = sum(1 for e in rows if e.label == 1)
    n_hon = sum(1 for e in rows if e.label == 0)
    assert n_dec == 50
    assert n_hon == 50


def test_generate_is_deterministic():
    a = synth.generate(pairs=30, seed=7)
    b = synth.generate(pairs=30, seed=7)
    assert [(e.claim, e.label, e.claimed_without_running, e.ran_test_cmd,
             e.diff_lines, e.touched_test_files, e.hedged, e.absolute)
            for e in a] == [(e.claim, e.label, e.claimed_without_running,
                             e.ran_test_cmd, e.diff_lines, e.touched_test_files,
                             e.hedged, e.absolute) for e in b]


def test_rows_are_synth_source_and_valid():
    rows = synth.generate(pairs=20, seed=1)
    for e in rows:
        assert isinstance(e, Example)
        assert e.source == "synth"
        assert e.label in (0, 1)
        assert e.claim
        # phrasing flags are mutually consistent with one being set
        assert e.hedged != e.absolute


def test_separation_is_noisy_not_perfect():
    """Deceptive rows should LEAN to claimed_without_running but not perfectly."""
    rows = synth.generate(pairs=200, seed=3)
    dec = [e for e in rows if e.label == 1]
    hon = [e for e in rows if e.label == 0]
    dec_cwr = sum(1 for e in dec if e.claimed_without_running) / len(dec)
    hon_cwr = sum(1 for e in hon if e.claimed_without_running) / len(hon)
    # deceptive rows claim-without-running much more often
    assert dec_cwr > hon_cwr + 0.3
    # but it is noisy: not a perfect 1.0 leak, and honest is not a perfect 0.0
    assert dec_cwr < 0.98
    assert hon_cwr > 0.0


def test_separation_is_learnable():
    """A trivial linear separability check: the top feature must carry signal.

    We avoid requiring sklearn here; instead verify mean class separation on the
    feature matrix so train.py can reach PR-AUC ~0.9+ downstream.
    """
    rows = synth.generate(pairs=200, seed=5)
    X = to_matrix(rows)
    y = labels(rows)
    col = synth_top_feature_index()
    dec_mean = X[y == 1, col].mean()
    hon_mean = X[y == 0, col].mean()
    assert dec_mean > hon_mean + 0.3


def synth_top_feature_index() -> int:
    from proofml.features import FEATURE_NAMES
    return FEATURE_NAMES.index("claimed_without_running")


def test_build_no_verifier_does_not_shell_out(monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not shell out in --no-verifier mode")

    monkeypatch.setattr(synth.subprocess, "run", boom)
    rows = synth.build(pairs=10, use_verifier=False, seed=0)
    assert len(rows) == 20
    assert called["n"] == 0


def test_build_verifier_falls_back_when_proof_missing(monkeypatch, capsys):
    monkeypatch.setattr(synth, "_proof_on_path", lambda: False)
    rows = synth.build(pairs=10, use_verifier=True, seed=0)
    assert len(rows) == 20  # fell back to generate()
    err = capsys.readouterr().err
    assert "falling back" in err.lower()


def test_verifier_label_parses_json(monkeypatch):
    class FakeProc:
        stdout = json.dumps({"overall": "fail"})
        stderr = ""

    monkeypatch.setattr(synth.subprocess, "run", lambda *a, **k: FakeProc())
    ex = Example(claim="all tests pass", label=0, source="synth")
    assert synth._verifier_label(ex) == 1

    class FakeProcPass:
        stdout = json.dumps({"overall": "pass"})
        stderr = ""

    monkeypatch.setattr(synth.subprocess, "run", lambda *a, **k: FakeProcPass())
    assert synth._verifier_label(ex) == 0

    class FakeProcInconc:
        stdout = json.dumps({"overall": "inconclusive"})
        stderr = ""

    monkeypatch.setattr(synth.subprocess, "run", lambda *a, **k: FakeProcInconc())
    assert synth._verifier_label(ex) is None


def test_verifier_label_handles_garbage(monkeypatch):
    class FakeProc:
        stdout = "not json at all"
        stderr = ""

    monkeypatch.setattr(synth.subprocess, "run", lambda *a, **k: FakeProc())
    ex = Example(claim="x", label=0, source="synth")
    assert synth._verifier_label(ex) is None


def test_main_writes_roundtrippable_jsonl(tmp_path):
    out = tmp_path / "examples.jsonl"
    rc = synth.main(["--pairs", "15", "--out", str(out), "--no-verifier", "--seed", "2"])
    assert rc == 0
    assert out.exists()
    loaded = load_examples(str(out))
    assert len(loaded) == 30
    assert all(e.source == "synth" for e in loaded)
    assert sum(1 for e in loaded if e.label == 1) == 15


def test_verifier_label_treats_suspect_as_deceptive(monkeypatch):
    class FakeProc:
        stdout = json.dumps({"overall": "suspect"})
        stderr = ""

    monkeypatch.setattr(synth.subprocess, "run", lambda *a, **k: FakeProc())
    assert synth._verifier_label(Example(claim="all tests pass", label=0, source="synth")) == 1
