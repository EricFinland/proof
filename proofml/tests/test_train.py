"""Deterministic tests for proofml.train.

Builds a tiny, separable, balanced dataset (honest vs deceptive) so a calibrated
baseline can actually learn the boundary, trains via the real CLI path, and
asserts the artifacts and metrics are well formed. Everything is seeded.

Skips cleanly if scikit-learn / joblib are not installed.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from proofml.data import write_examples
from proofml.schema import Example

pytest.importorskip("sklearn")
pytest.importorskip("joblib")

from proofml import train  # noqa: E402  (imported after importorskip)


def _make_dataset(n_per_class: int = 30, seed: int = 7):
    """Build a balanced, learnably-separable set of Examples with noise.

    Deceptive rows correlate (noisily) with claimed_without_running=True and
    ran_test_cmd=False; honest rows are the opposite. Claim text varies between
    absolute and hedged phrasings so claim-text features carry signal too.
    """
    rng = random.Random(seed)
    rows = []

    deceptive_claims = [
        "All tests pass and the build is green.",
        "Done, everything works.",
        "The feature is complete and fully tested.",
    ]
    honest_claims = [
        "I think this should pass, but please double check.",
        "Probably works, I did not run the full suite.",
        "This might fix it; verification still pending.",
    ]

    for _ in range(n_per_class):
        # Deceptive: ~85% claimed_without_running True, ran_test_cmd False.
        cwr = rng.random() < 0.85
        ran = rng.random() < 0.15
        rows.append(
            Example(
                claim=rng.choice(deceptive_claims),
                label=1,
                source="synth",
                ran_test_cmd=ran,
                claimed_without_running=cwr,
                diff_lines=rng.randint(5, 120),
                touched_test_files=rng.random() < 0.2,
                hedged=False,
                absolute=True,
            )
        )
        # Honest: mostly ran the check, rarely claimed without running.
        cwr_h = rng.random() < 0.15
        ran_h = rng.random() < 0.85
        rows.append(
            Example(
                claim=rng.choice(honest_claims),
                label=0,
                source="synth",
                ran_test_cmd=ran_h,
                claimed_without_running=cwr_h,
                diff_lines=rng.randint(5, 120),
                touched_test_files=rng.random() < 0.7,
                hedged=True,
                absolute=False,
            )
        )

    rng.shuffle(rows)
    return rows


def test_train_produces_artifacts_and_metrics(tmp_path: Path):
    data_path = tmp_path / "examples.jsonl"
    out_dir = tmp_path / "artifacts"
    write_examples(_make_dataset(), str(data_path))

    model_path, metrics_path, metrics = train.train(
        str(data_path), str(out_dir), seed=1337
    )

    assert Path(model_path).exists()
    assert Path(metrics_path).exists()

    # Metrics file is valid JSON with the contract keys.
    on_disk = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
    for key in (
        "pr_auc",
        "roc_auc",
        "brier",
        "precision",
        "recall",
        "f1",
        "chosen_model",
    ):
        assert key in on_disk

    assert on_disk["chosen_model"] in (
        "logistic_regression",
        "gradient_boosting",
    )
    # Metrics are in valid ranges.
    for key in ("pr_auc", "roc_auc", "precision", "recall", "f1"):
        assert 0.0 <= on_disk[key] <= 1.0
    assert 0.0 <= on_disk["brier"] <= 1.0


def test_separable_data_is_learnable(tmp_path: Path):
    """A separable signal should yield a clearly-better-than-chance PR-AUC."""
    data_path = tmp_path / "examples.jsonl"
    out_dir = tmp_path / "artifacts"
    write_examples(_make_dataset(n_per_class=60), str(data_path))

    _, _, metrics = train.train(str(data_path), str(out_dir), seed=1337)
    assert metrics["pr_auc"] >= 0.7


def test_loaded_model_predicts_probabilities(tmp_path: Path):
    """The saved joblib model loads and yields per-row deceptive probabilities."""
    import joblib

    from proofml.features import to_matrix

    data_path = tmp_path / "examples.jsonl"
    out_dir = tmp_path / "artifacts"
    rows = _make_dataset()
    write_examples(rows, str(data_path))

    model_path, _, _ = train.train(str(data_path), str(out_dir), seed=1337)
    model = joblib.load(model_path)

    proba = model.predict_proba(to_matrix(rows[:5]))
    assert proba.shape == (5, 2)
    # Probabilities sum to 1 per row.
    assert all(abs(p.sum() - 1.0) < 1e-6 for p in proba)


def test_determinism(tmp_path: Path):
    """Two runs with the same seed produce identical metrics."""
    rows = _make_dataset()
    data_path = tmp_path / "examples.jsonl"
    write_examples(rows, str(data_path))

    _, _, m1 = train.train(str(data_path), str(tmp_path / "a"), seed=1337)
    _, _, m2 = train.train(str(data_path), str(tmp_path / "b"), seed=1337)

    assert m1["pr_auc"] == m2["pr_auc"]
    assert m1["chosen_model"] == m2["chosen_model"]
    assert m1["brier"] == m2["brier"]


def test_single_class_raises(tmp_path: Path):
    """All-honest data cannot train a deception boundary and must error out."""
    rows = [
        Example(claim="works", label=0, source="synth")
        for _ in range(6)
    ]
    data_path = tmp_path / "examples.jsonl"
    write_examples(rows, str(data_path))

    with pytest.raises(SystemExit):
        train.train(str(data_path), str(tmp_path / "out"), seed=1337)
