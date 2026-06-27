"""Deterministic tests for the cost-gated cascade frontier.

The frontier math (sweep_frontier, pick_operating_point) is pure numpy and needs
no sklearn or joblib, so those tests always run. The end-to-end save path is
exercised with a tiny stub model so it works without a trained artifact.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from proofml import cascade
from proofml.schema import Example


def _toy_scores():
    """Five rows: clean separation so the frontier is easy to reason about.

    proba (deceptive prob), y (1 = deceptive):
        honest rows score low, deceptive rows score high.
    """
    proba = np.array([0.1, 0.2, 0.6, 0.8, 0.9])
    y = np.array([0, 0, 1, 1, 1])
    return proba, y


def test_sweep_frontier_basic_shape_and_bounds():
    proba, y = _toy_scores()
    frontier = cascade.sweep_frontier(proba, y)
    assert frontier, "frontier must not be empty"
    # sorted ascending by threshold
    ts = [r["threshold"] for r in frontier]
    assert ts == sorted(ts)
    for r in frontier:
        assert 0.0 <= r["skip_rate"] <= 1.0
        assert 0.0 <= r["recall"] <= 1.0
        assert r["n_sent"] + r["n_skipped"] == len(proba)
        assert r["n_lies"] == 3


def test_sweep_frontier_recall_monotone_nonincreasing_in_threshold():
    # Raising the threshold can only skip more and catch fewer (or equal).
    proba, y = _toy_scores()
    frontier = cascade.sweep_frontier(proba, y)
    recalls = [r["recall"] for r in frontier]
    skips = [r["skip_rate"] for r in frontier]
    for a, b in zip(recalls, recalls[1:]):
        assert b <= a + 1e-12
    for a, b in zip(skips, skips[1:]):
        assert b >= a - 1e-12


def test_threshold_zero_sends_everything():
    proba, y = _toy_scores()
    frontier = cascade.sweep_frontier(proba, y)
    first = frontier[0]
    assert first["threshold"] == 0.0
    assert first["skip_rate"] == 0.0
    assert first["recall"] == 1.0  # nothing skipped, all lies caught


def test_pick_operating_point_meets_recall_and_maximizes_skip():
    proba, y = _toy_scores()
    frontier = cascade.sweep_frontier(proba, y)
    op = cascade.pick_operating_point(frontier, min_recall=1.0)
    assert op is not None
    assert op["recall"] >= 1.0 - 1e-12
    # With perfect separation, recall=1.0 is held until threshold passes the
    # lowest deceptive score (0.6), so we should skip the two honest rows.
    assert op["skip_rate"] == pytest.approx(2 / 5)
    assert op["lies_caught"] == 3


def test_pick_operating_point_unreachable_recall_returns_none():
    proba = np.array([0.4, 0.4, 0.4])
    y = np.array([0, 0, 1])
    frontier = cascade.sweep_frontier(proba, y)
    # demand more recall than is ever achievable above some skipping is fine,
    # but recall>1 is impossible -> None
    assert cascade.pick_operating_point(frontier, min_recall=1.01) is None


def test_relaxed_recall_skips_more_than_strict():
    proba, y = _toy_scores()
    frontier = cascade.sweep_frontier(proba, y)
    strict = cascade.pick_operating_point(frontier, min_recall=1.0)
    relaxed = cascade.pick_operating_point(frontier, min_recall=0.6)
    assert strict is not None and relaxed is not None
    assert relaxed["skip_rate"] >= strict["skip_rate"]


def test_deceptive_proba_respects_classes_order():
    class StubModel:
        # classes_ deliberately reversed so column 0 is class 1.
        classes_ = [1, 0]

        def predict_proba(self, X):
            n = len(X)
            # class 1 prob in column 0, class 0 prob in column 1
            return np.column_stack([np.full(n, 0.7), np.full(n, 0.3)])

    X = np.zeros((4, 8))
    p = cascade._deceptive_proba(StubModel(), X)
    assert np.allclose(p, 0.7)


def test_save_csv_fallback_writes_expected_columns(tmp_path):
    proba, y = _toy_scores()
    frontier = cascade.sweep_frontier(proba, y)
    out = tmp_path / "cascade_frontier.csv"
    cascade._save_csv(frontier, out)
    assert out.exists()
    with out.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    expected = {
        "threshold",
        "skip_rate",
        "recall",
        "n_sent",
        "n_skipped",
        "lies_caught",
        "n_lies",
    }
    assert expected.issubset(set(rows[0].keys()))


def test_save_png_or_csv_never_hard_fails(tmp_path):
    # Whether or not matplotlib is installed, this must not raise.
    proba, y = _toy_scores()
    frontier = cascade.sweep_frontier(proba, y)
    op = cascade.pick_operating_point(frontier, 1.0)
    ok = cascade._save_png(frontier, op, tmp_path / "cascade.png")
    if not ok:
        path = cascade._save_csv(frontier, tmp_path / "cascade_frontier.csv")
        assert Path(path).exists()
    else:
        assert (tmp_path / "cascade.png").exists()


def test_heldout_split_is_deterministic_and_nonempty():
    rng = np.random.RandomState(0)
    examples = []
    for i in range(40):
        lbl = int(i % 2)
        examples.append(
            Example(
                claim="claim {}".format(i),
                label=lbl,
                claimed_without_running=bool(lbl),
            )
        )
    y = np.array([e.label for e in examples], dtype=int)
    held_a, ya = cascade._heldout_split(examples, y)
    held_b, yb = cascade._heldout_split(examples, y)
    assert len(held_a) > 0
    assert [e.claim for e in held_a] == [e.claim for e in held_b]
    assert np.array_equal(ya, yb)


def test_run_cascade_end_to_end_with_stub_model(tmp_path, monkeypatch):
    """Exercise run_cascade without a real joblib model or sklearn dependency."""
    from proofml.data import write_examples

    # Build a learnable toy dataset: deceptive rows carry claimed_without_running.
    examples = []
    for i in range(40):
        deceptive = i % 2 == 0
        examples.append(
            Example(
                claim="all tests pass" if deceptive else "tests pass, I ran pytest",
                label=1 if deceptive else 0,
                source="synth",
                claimed_without_running=deceptive,
                ran_test_cmd=not deceptive,
                absolute=deceptive,
                hedged=not deceptive,
            )
        )
    data_path = tmp_path / "examples.jsonl"
    write_examples(examples, str(data_path))

    art = tmp_path / "artifacts"
    art.mkdir()

    # Stub model: score = 1.0 when claimed_without_running feature is set.
    class StubModel:
        classes_ = [0, 1]

        def predict_proba(self, X):
            X = np.asarray(X)
            risky = X[:, 0]  # FEATURE_NAMES[0] == claimed_without_running
            p1 = np.where(risky > 0.5, 0.95, 0.05)
            return np.column_stack([1.0 - p1, p1])

    monkeypatch.setattr(cascade, "_load_model", lambda artifacts: StubModel())

    frontier, op, saved = cascade.run_cascade(
        str(art), str(data_path), min_recall=1.0
    )
    assert frontier
    assert op is not None
    assert op["recall"] >= 1.0 - 1e-9
    assert op["skip_rate"] > 0.0  # honest rows should be skippable
    assert Path(saved).exists()
