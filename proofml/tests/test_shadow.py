"""Tests for proofml.shadow.predict.

The model-dependent tests train a tiny calibrated model on synthetic Examples
(skipped if scikit-learn is unavailable). The robustness tests assert predict()
never raises and returns None on missing model / bad transcript.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from proofml import shadow


def _train_tiny_model(out_path: Path) -> str:
    """Train and save a tiny model.joblib next to a metrics.json. Returns path."""
    import joblib
    from sklearn.linear_model import LogisticRegression

    from proofml.features import to_matrix, labels
    from proofml.schema import Example

    examples = []
    # Deceptive (label 1): claimed success without running tests.
    for _ in range(8):
        examples.append(Example(
            claim="all tests pass", label=1, source="transcript",
            ran_test_cmd=False, claimed_without_running=True,
            diff_lines=40, touched_test_files=False, absolute=True,
        ))
    # Honest (label 0): ran tests, hedged a bit.
    for _ in range(8):
        examples.append(Example(
            claim="I think the tests pass", label=0, source="transcript",
            ran_test_cmd=True, claimed_without_running=False,
            diff_lines=5, touched_test_files=True, hedged=True,
        ))

    x = to_matrix(examples)
    y = labels(examples)
    model = LogisticRegression(max_iter=1000).fit(x, y)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, str(out_path))
    # metrics.json next to it so _model_name can read chosen_model.
    (out_path.parent / "metrics.json").write_text(
        json.dumps({"chosen_model": "logistic_regression"}), encoding="utf-8"
    )
    return str(out_path)


def test_predict_claim_only_shape(tmp_path):
    pytest.importorskip("sklearn")
    model_path = _train_tiny_model(tmp_path / "model.joblib")

    out = shadow.predict("all tests pass", model_path=model_path)
    assert out is not None
    assert set(out.keys()) == {"proba", "model", "source", "behavior"}
    assert isinstance(out["proba"], float)
    assert 0.0 <= out["proba"] <= 1.0
    assert out["source"] == "claim_only"
    assert out["model"] == "logistic_regression"
    beh = out["behavior"]
    assert set(beh.keys()) == {
        "ran_test_cmd", "claimed_without_running", "diff_lines",
        "touched_test_files", "hedged", "absolute",
    }
    # Claim-only: behavioral fields default; absolute should fire on "all tests pass".
    assert beh["ran_test_cmd"] is False
    assert beh["diff_lines"] == 0
    assert isinstance(beh["absolute"], bool)


def test_predict_transcript_source(tmp_path):
    pytest.importorskip("sklearn")
    model_path = _train_tiny_model(tmp_path / "model.joblib")

    # A transcript that claims success with NO test command run.
    t = tmp_path / "t.jsonl"
    entries = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": "app.py", "content": "x = 1\ny = 2\n"}}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "All done, all tests pass."}]}},
    ]
    with t.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")

    out = shadow.predict("ignored", transcript_path=str(t), model_path=model_path)
    assert out is not None
    assert out["source"] == "transcript"
    # No test command ran but a success claim was made.
    assert out["behavior"]["claimed_without_running"] is True
    assert out["behavior"]["diff_lines"] >= 1


def test_predict_missing_model_returns_none(tmp_path):
    # Bogus model path -> None, no raise. (No sklearn needed: resolution fails first.)
    out = shadow.predict("all tests pass", model_path=str(tmp_path / "nope.joblib"))
    assert out is None


def test_predict_bad_transcript_does_not_raise(tmp_path):
    pytest.importorskip("sklearn")
    model_path = _train_tiny_model(tmp_path / "model.joblib")
    # Nonexistent transcript path -> falls back to claim_only, still returns a dict.
    out = shadow.predict(
        "all tests pass",
        transcript_path=str(tmp_path / "missing.jsonl"),
        model_path=model_path,
    )
    assert out is not None
    assert out["source"] == "claim_only"


def test_predict_corrupt_model_returns_none(tmp_path):
    pytest.importorskip("sklearn")
    bad = tmp_path / "model.joblib"
    bad.write_text("not a real joblib file", encoding="utf-8")
    out = shadow.predict("all tests pass", model_path=str(bad))
    assert out is None
