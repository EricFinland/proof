"""Cost-gated verification frontier.

proofml predicts whether an agent's success claim is deceptive before running
proof's expensive verifier. A cascade uses that prediction as a cheap gate: only
claims the model scores as risky (probability of deception at or above a
threshold) get sent to the real verifier. Everything below the threshold is
trusted and the verifier run is skipped, saving cost.

This module sweeps the decision threshold to trace the frontier between two
quantities:
  - SKIP RATE: the fraction of verifier runs we avoid (claims below threshold).
  - RECALL on deception: the fraction of true lies we still catch (true
    deceptive claims that land at or above the threshold, so they get verified).

Raising the threshold skips more runs but catches fewer lies. We pick the
operating point that skips the most runs while still meeting --min-recall, and
print it as a plain-English sentence. The frontier is saved to
artifacts/cascade.png when matplotlib is importable, otherwise to
artifacts/cascade_frontier.csv. Missing matplotlib never hard-fails the run.

Usage:
    python -m proofml.cascade --artifacts artifacts --data data/examples.jsonl \
        --min-recall 0.95
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from proofml.data import load_examples
from proofml.features import to_matrix, labels


# Fallback split parameters, used ONLY when artifacts/heldout.jsonl is absent
# (e.g. a model trained by an older proofml). These mirror train.py's defaults
# so the fallback is at least consistent, but the authoritative held-out set is
# the heldout.jsonl that train.py writes; prefer it whenever it exists.
HELDOUT_TEST_SIZE = 0.3
SPLIT_SEED = 1337


def _heldout_split(examples: List, y: np.ndarray):
    """Return the held-out subset of examples using train.py's split.

    Mirrors train.py: a single stratified train_test_split with a fixed seed.
    Falls back to a deterministic index split if sklearn is unavailable or
    stratification is impossible (degenerate class counts).
    """
    n = len(examples)
    idx = np.arange(n)
    try:
        from sklearn.model_selection import train_test_split

        stratify = y if (len(np.unique(y)) > 1 and np.min(np.bincount(y)) >= 2) else None
        _, test_idx = train_test_split(
            idx,
            test_size=HELDOUT_TEST_SIZE,
            random_state=SPLIT_SEED,
            stratify=stratify,
        )
    except Exception:
        rng = np.random.RandomState(SPLIT_SEED)
        shuffled = idx.copy()
        rng.shuffle(shuffled)
        cut = max(1, int(round(n * HELDOUT_TEST_SIZE)))
        test_idx = shuffled[:cut]

    test_idx = np.sort(np.asarray(test_idx, dtype=int))
    held = [examples[i] for i in test_idx]
    return held, y[test_idx]


def _deceptive_proba(model, X: np.ndarray) -> np.ndarray:
    """Probability of the deceptive class (label 1) for each row.

    Handles models whose classes_ order may differ; falls back to decision_function
    or raw predictions if predict_proba is missing.
    """
    if hasattr(model, "predict_proba"):
        proba = np.asarray(model.predict_proba(X))
        classes = list(getattr(model, "classes_", [0, 1]))
        try:
            col = classes.index(1)
        except ValueError:
            col = proba.shape[1] - 1
        return proba[:, col]
    if hasattr(model, "decision_function"):
        scores = np.asarray(model.decision_function(X), dtype=float)
        lo, hi = float(np.min(scores)), float(np.max(scores))
        if hi > lo:
            return (scores - lo) / (hi - lo)
        return np.full_like(scores, 0.5)
    return np.asarray(model.predict(X), dtype=float)


def sweep_frontier(
    proba: np.ndarray, y: np.ndarray, n_points: int = 101
) -> List[dict]:
    """Sweep the decision threshold and report skip rate and recall at each.

    For a threshold t, a claim is SENT to the verifier when proba >= t and
    SKIPPED otherwise. So:
        skip_rate = mean(proba < t)                  over all held-out rows
        recall    = (# true lies with proba >= t) / (# true lies)
    Returns one dict per threshold, sorted by ascending threshold.
    """
    proba = np.asarray(proba, dtype=float)
    y = np.asarray(y, dtype=int)
    n = len(proba)
    n_pos = int(np.sum(y == 1))

    # Thresholds spanning [0, 1] plus the exact observed scores, so every
    # reachable operating point is represented.
    grid = np.linspace(0.0, 1.0, n_points)
    thresholds = np.unique(np.concatenate([grid, proba, [0.0, 1.0]]))
    thresholds = np.clip(thresholds, 0.0, 1.0)

    rows: List[dict] = []
    for t in thresholds:
        sent = proba >= t
        skipped = ~sent
        skip_rate = float(np.mean(skipped)) if n else 0.0
        if n_pos:
            caught = int(np.sum((y == 1) & sent))
            recall = caught / n_pos
        else:
            caught = 0
            recall = 1.0  # no lies to miss; treat as fully covered
        rows.append(
            {
                "threshold": float(t),
                "skip_rate": skip_rate,
                "recall": float(recall),
                "n_sent": int(np.sum(sent)),
                "n_skipped": int(np.sum(skipped)),
                "lies_caught": caught,
                "n_lies": n_pos,
            }
        )
    rows.sort(key=lambda r: r["threshold"])
    return rows


def pick_operating_point(
    frontier: List[dict], min_recall: float
) -> Optional[dict]:
    """Choose the point that skips the most runs while recall >= min_recall.

    Among all thresholds meeting the recall floor, return the one with the
    highest skip rate (ties broken by the higher threshold, which skips at least
    as much). Returns None if no threshold meets the floor.
    """
    eligible = [r for r in frontier if r["recall"] >= min_recall]
    if not eligible:
        return None
    eligible.sort(key=lambda r: (r["skip_rate"], r["threshold"]))
    return eligible[-1]


def _save_png(frontier: List[dict], op: Optional[dict], out_path: Path) -> bool:
    """Plot the frontier to a PNG. Returns True on success, False if no matplotlib."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False

    skip = [r["skip_rate"] * 100.0 for r in frontier]
    recall = [r["recall"] * 100.0 for r in frontier]

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(skip, recall, color="#0aa", lw=2, label="cascade frontier")
    ax.set_xlabel("verifier runs skipped (%)")
    ax.set_ylabel("lies caught / recall (%)")
    ax.set_title("Cost-gated verification frontier")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3)

    if op is not None:
        ox = op["skip_rate"] * 100.0
        oy = op["recall"] * 100.0
        ax.scatter([ox], [oy], color="#e4572e", zorder=5, s=60)
        ax.annotate(
            "skip {:.0f}% / catch {:.0f}%".format(ox, oy),
            xy=(ox, oy),
            xytext=(8, -14),
            textcoords="offset points",
            fontsize=9,
            color="#e4572e",
        )
    ax.legend(loc="lower left")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return True


def _save_csv(frontier: List[dict], out_path: Path) -> str:
    """Write the frontier to CSV (fallback when matplotlib is missing)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "threshold",
        "skip_rate",
        "recall",
        "n_sent",
        "n_skipped",
        "lies_caught",
        "n_lies",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in frontier:
            w.writerow({c: r[c] for c in cols})
    return str(out_path)


def _write_operating_point(
    op: Optional[dict], min_recall: float, model_name: str, n_held: int, out_path: Path
) -> str:
    """Persist the calibrated operating point the live gate reads.

    Writes artifacts/operating_point.json with the chosen threshold and the
    cascade stats behind it. None-safe: when no operating point meets the recall
    floor, threshold is written as null (the gate then falls back to its own
    default and never skips on a missing/None threshold).
    """
    if op is not None:
        payload = {
            "threshold": float(op["threshold"]),
            "min_recall": float(min_recall),
            "recall": float(op["recall"]),
            "skip_rate": float(op["skip_rate"]),
            "model": model_name,
            "n_held": int(n_held),
            "n_lies": int(op.get("n_lies", 0)),
        }
    else:
        payload = {
            "threshold": None,
            "min_recall": float(min_recall),
            "recall": None,
            "skip_rate": None,
            "model": model_name,
            "n_held": int(n_held),
            "n_lies": None,
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out_path)


def _model_name(artifacts: str) -> str:
    """Best-effort model name from metrics.json chosen_model, else 'model'."""
    try:
        metrics = Path(artifacts) / "metrics.json"
        if metrics.is_file():
            data = json.loads(metrics.read_text(encoding="utf-8"))
            name = data.get("chosen_model")
            if isinstance(name, str) and name:
                return name
    except Exception:
        pass
    return "model"


def _load_model(artifacts: str):
    """Load the fitted calibrated estimator saved by train.py."""
    import joblib

    model_path = Path(artifacts) / "model.joblib"
    if not model_path.exists():
        raise FileNotFoundError(
            "model.joblib not found at {}. Run `python -m proofml.train` first.".format(
                model_path
            )
        )
    return joblib.load(model_path)


def run_cascade(
    artifacts: str, data: str, min_recall: float
) -> Tuple[List[dict], Optional[dict], str]:
    """End-to-end: load model + data, sweep, pick operating point, save artifact.

    Returns (frontier, operating_point_or_None, saved_artifact_path).
    """
    # Prefer the authoritative held-out set train.py persisted; only fall back to
    # re-deriving a split when it is missing. This is what makes the frontier
    # honest: these rows are exactly the ones the model never trained on.
    heldout_path = Path(artifacts) / "heldout.jsonl"
    if heldout_path.exists():
        held = load_examples(str(heldout_path))
        if not held:
            raise ValueError("held-out set at {} is empty".format(heldout_path))
        y_held = labels(held)
    else:
        examples = load_examples(data)
        if not examples:
            raise ValueError("no labeled examples loaded from {}".format(data))
        print(
            "note: {} not found; re-deriving the held-out split from --data. "
            "Re-run `python -m proofml.train` to persist the authoritative "
            "held-out set.".format(heldout_path)
        )
        y = labels(examples)
        held, y_held = _heldout_split(examples, y)
        if not held:
            raise ValueError("held-out split is empty; need more data")

    X_held = to_matrix(held)
    model = _load_model(artifacts)
    proba = _deceptive_proba(model, X_held)

    frontier = sweep_frontier(proba, y_held)
    op = pick_operating_point(frontier, min_recall)

    art_dir = Path(artifacts)

    # Persist the calibrated operating point the live gate reads (additive; does
    # not change the existing frontier outputs/metrics below).
    op_path = art_dir / "operating_point.json"
    model_name = _model_name(artifacts)
    _write_operating_point(op, min_recall, model_name, len(held), op_path)
    if op is None:
        print(
            "note: no operating point meets min-recall {:.1%}; wrote "
            "operating_point.json with threshold=null (gate will not skip).".format(
                min_recall
            )
        )

    png_path = art_dir / "cascade.png"
    if _save_png(frontier, op, png_path):
        saved = str(png_path)
    else:
        saved = _save_csv(frontier, art_dir / "cascade_frontier.csv")
        print(
            "matplotlib not available; wrote frontier CSV instead of PNG: {}".format(
                saved
            )
        )
    return frontier, op, saved


def _print_report(
    frontier: List[dict], op: Optional[dict], min_recall: float, n_held: int
) -> None:
    """Print a readable summary of the frontier and the chosen operating point."""
    n_lies = frontier[0]["n_lies"] if frontier else 0
    print("=" * 60)
    print("proofml cascade: cost-gated verification frontier")
    print("=" * 60)
    print("held-out rows : {}".format(n_held))
    print("deceptive rows: {}".format(n_lies))
    print("min-recall    : {:.1%}".format(min_recall))
    print("-" * 60)

    # A few representative rows across the frontier.
    print("threshold   skip%    recall%   sent   skipped")
    step = max(1, len(frontier) // 10)
    for r in frontier[::step]:
        print(
            "{:>8.3f}  {:>6.1f}   {:>6.1f}   {:>4d}   {:>5d}".format(
                r["threshold"],
                r["skip_rate"] * 100.0,
                r["recall"] * 100.0,
                r["n_sent"],
                r["n_skipped"],
            )
        )
    print("-" * 60)

    if op is None:
        best = max(frontier, key=lambda r: r["recall"]) if frontier else None
        print(
            "No operating point reaches recall >= {:.1%}.".format(min_recall)
        )
        if best is not None:
            print(
                "Best achievable recall is {:.1%} (skips {:.1%} of verifier runs).".format(
                    best["recall"], best["skip_rate"]
                )
            )
        print("Lower --min-recall or gather more training data.")
        return

    print(
        "OPERATING POINT (threshold {:.3f}):".format(op["threshold"])
    )
    print(
        "  Skip {:.0f}% of verifier runs while catching {:.0f}% of lies.".format(
            op["skip_rate"] * 100.0, op["recall"] * 100.0
        )
    )
    print(
        "  ({} of {} runs skipped; {} of {} lies caught.)".format(
            op["n_skipped"], n_held, op["lies_caught"], op["n_lies"]
        )
    )


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m proofml.cascade",
        description="Sweep the cost-gated verification frontier for a trained proofml model.",
    )
    ap.add_argument(
        "--artifacts",
        default="artifacts",
        help="directory holding model.joblib (default: artifacts)",
    )
    ap.add_argument(
        "--data",
        default="data/examples.jsonl",
        help="examples.jsonl to score the held-out split from",
    )
    ap.add_argument(
        "--min-recall",
        type=float,
        default=0.95,
        help="minimum recall on deception the operating point must meet (default: 0.95)",
    )
    args = ap.parse_args(argv)

    frontier, op, saved = run_cascade(args.artifacts, args.data, args.min_recall)

    # Recompute held count for the report from the frontier (sent+skipped is total).
    n_held = (frontier[0]["n_sent"] + frontier[0]["n_skipped"]) if frontier else 0
    _print_report(frontier, op, args.min_recall, n_held)
    print("-" * 60)
    print("saved frontier artifact: {}".format(saved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
