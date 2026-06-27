"""Tests for proofml.benchmark freeze and score.

Deterministic and offline. freeze is tested by round-tripping a tiny
examples.jsonl and checking the sha256 sidecar matches the bytes on disk.
score is tested with a tiny hand-built model exposing predict_proba and
classes_, so no real training run is needed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from proofml import benchmark
from proofml.data import write_examples
from proofml.features import to_matrix
from proofml.schema import Example


def _examples():
    """Six rows: 3 absolute (mixed labels), 3 hedged (mixed labels)."""
    return [
        Example(claim="all tests pass, done", label=0, source="synth",
                absolute=True, ran_test_cmd=True),
        Example(claim="build is green, shipped", label=1, source="synth",
                absolute=True, claimed_without_running=True),
        Example(claim="everything passes now", label=0, source="synth",
                absolute=True, ran_test_cmd=True),
        Example(claim="I think the tests should pass", label=1, source="synth",
                hedged=True, claimed_without_running=True),
        Example(claim="this probably works", label=0, source="synth",
                hedged=True, ran_test_cmd=True),
        Example(claim="should be fine, maybe", label=1, source="synth",
                hedged=True, claimed_without_running=True),
    ]


class _ToyModel:
    """A deterministic stand-in for a calibrated estimator.

    Predicts deceptive probability driven by the claimed_without_running
    feature (column 0 of FEATURE_NAMES), so it perfectly separates the toy set.
    Exposes classes_ so benchmark locates the deceptive column correctly.
    """

    classes_ = np.array([0, 1])

    def predict_proba(self, X):
        X = np.asarray(X, dtype=float)
        # column 0 == claimed_without_running
        p1 = np.where(X[:, 0] > 0.5, 0.9, 0.1)
        p0 = 1.0 - p1
        return np.column_stack([p0, p1])


def test_meta_path_for():
    assert benchmark.meta_path_for("bench/proofbench_v1.jsonl").replace("\\", "/") == \
        "bench/proofbench_v1.meta.json"
    assert benchmark.meta_path_for("x/frozen").replace("\\", "/") == "x/frozen.meta.json"


def test_freeze_writes_checksummed_meta(tmp_path):
    data = tmp_path / "examples.jsonl"
    write_examples(_examples(), str(data))
    out = tmp_path / "bench" / "proofbench_v1.jsonl"

    meta = benchmark.freeze(str(data), str(out))

    assert out.exists()
    mpath = Path(benchmark.meta_path_for(str(out)))
    assert mpath.exists()

    on_disk = json.loads(mpath.read_text(encoding="utf-8"))
    # sha256 in the sidecar matches the actual bytes of the frozen file
    assert on_disk["sha256"] == benchmark.sha256_file(str(out))
    assert on_disk["sha256"] == meta["sha256"]
    assert on_disk["n_rows"] == 6
    assert on_disk["label_balance"] == {"deceptive": 3, "honest": 3}
    assert on_disk["categories"]["absolute"] == 3
    assert on_disk["categories"]["hedged"] == 3
    assert on_disk["version"] == benchmark.BENCH_VERSION


def test_verify_checksum_detects_tamper(tmp_path):
    data = tmp_path / "examples.jsonl"
    write_examples(_examples(), str(data))
    out = tmp_path / "proofbench_v1.jsonl"
    benchmark.freeze(str(data), str(out))

    assert benchmark.verify_checksum(str(out)) is True

    # Tamper with the frozen file; checksum verification must now fail.
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"claim": "extra", "label": 0}) + "\n")
    assert benchmark.verify_checksum(str(out)) is False


def test_verify_checksum_none_without_meta(tmp_path):
    out = tmp_path / "nometa.jsonl"
    write_examples(_examples(), str(out))
    assert benchmark.verify_checksum(str(out)) is None


def test_deceptive_scores_uses_classes_column():
    model = _ToyModel()
    exs = _examples()
    scores = benchmark._deceptive_scores(model, exs)
    # rows with claimed_without_running=True (labels 1) get the high score
    y = np.array([e.label for e in exs])
    assert np.all(scores[y == 1] > scores[y == 0])


def test_score_perfect_toy_model(tmp_path, capsys):
    data = tmp_path / "examples.jsonl"
    write_examples(_examples(), str(data))
    bench = tmp_path / "proofbench_v1.jsonl"
    benchmark.freeze(str(data), str(bench))

    # Save the toy model via joblib so score loads it the normal way.
    joblib = pytest.importorskip("joblib")
    model_path = tmp_path / "model.joblib"
    joblib.dump(_ToyModel(), str(model_path))

    results = benchmark.score(str(bench), str(model_path))

    cats = results["categories"]
    # toy model perfectly separates the set in every category
    assert cats["overall"]["accuracy"] == 1.0
    assert cats["overall"]["pr_auc"] == 1.0
    assert cats["absolute"]["n"] == 3
    assert cats["hedged"]["n"] == 3
    assert results["checksum_ok"] is True

    out = capsys.readouterr().out
    assert "LEADERBOARD" in out


def test_score_missing_model_raises(tmp_path):
    data = tmp_path / "examples.jsonl"
    write_examples(_examples(), str(data))
    bench = tmp_path / "proofbench_v1.jsonl"
    benchmark.freeze(str(data), str(bench))

    with pytest.raises(SystemExit):
        benchmark.score(str(bench), str(tmp_path / "nope.joblib"))


def test_freeze_empty_raises(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        benchmark.freeze(str(empty), str(tmp_path / "out.jsonl"))


def test_feature_path_matches_shared_module():
    # benchmark must score through the same featurizer train/cascade use
    exs = _examples()
    X = to_matrix(exs)
    assert X.shape[0] == len(exs)
