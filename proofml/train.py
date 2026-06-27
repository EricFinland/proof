"""Train two calibrated deception baselines and keep the better one.

Trains a calibrated LogisticRegression and a calibrated GradientBoostingClassifier,
picks the winner by PR-AUC (average precision) on a held-out split, and saves the
chosen fitted calibrated estimator to artifacts/model.joblib alongside a metrics
summary in artifacts/metrics.json.

Featurization goes through proofml.features.to_matrix so train, cascade, and
benchmark all share exactly one feature path.

CLI:
    python -m proofml.train --data data/examples.jsonl --out artifacts
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from proofml.data import load_examples, write_examples
from proofml.features import to_matrix, labels


SEED = 1337


def _seed_everything(seed: int = SEED) -> None:
    """Seed stdlib and numpy RNGs so a run is reproducible."""
    random.seed(seed)
    np.random.seed(seed)


def _build_models(seed: int = SEED):
    """Return {name: estimator} of calibrated baselines.

    Each base estimator is wrapped in CalibratedClassifierCV so predict_proba is
    well calibrated. Imports live here so the module imports cleanly even when
    scikit-learn is not installed (e.g. during a syntax-only check).
    """
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    logreg = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=1000, random_state=seed),
    )
    gboost = GradientBoostingClassifier(random_state=seed)

    return {
        "logistic_regression": CalibratedClassifierCV(
            logreg, method="sigmoid", cv=3
        ),
        "gradient_boosting": CalibratedClassifierCV(
            gboost, method="sigmoid", cv=3
        ),
    }


def _split(
    x: np.ndarray, y: np.ndarray, test_size: float = 0.3, seed: int = SEED
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Stratified train/test split, falling back to a plain split if stratify fails."""
    from sklearn.model_selection import train_test_split

    try:
        return train_test_split(
            x, y, test_size=test_size, random_state=seed, stratify=y
        )
    except ValueError:
        # Too few samples in a class to stratify; do an unstratified split.
        return train_test_split(x, y, test_size=test_size, random_state=seed)


def _split_indices(
    y: np.ndarray, test_size: float = 0.3, seed: int = SEED
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (train_idx, test_idx) for a stratified split over row positions.

    train_test_split computes its partition from n_samples + random_state and
    then indexes every array it is given, so splitting the index array yields the
    exact same partition as splitting x/y directly. We split indices so the
    held-out *examples* can be recovered and persisted for the cascade, which
    must score the model's untouched test set rather than re-deriving a split.
    """
    from sklearn.model_selection import train_test_split

    idx = np.arange(len(y))
    try:
        return train_test_split(
            idx, test_size=test_size, random_state=seed, stratify=y
        )
    except ValueError:
        return train_test_split(idx, test_size=test_size, random_state=seed)


def _evaluate(y_true: np.ndarray, proba: np.ndarray) -> Dict[str, float]:
    """Compute the full metric set from true labels and deceptive-class probability."""
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    pred = (proba >= 0.5).astype(int)

    # PR-AUC and ROC-AUC need both classes present in y_true to be meaningful.
    both_classes = len(np.unique(y_true)) > 1
    pr_auc = float(average_precision_score(y_true, proba)) if both_classes else 0.0
    roc_auc = float(roc_auc_score(y_true, proba)) if both_classes else 0.0

    return {
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "brier": float(brier_score_loss(y_true, proba)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
    }


def _proba_deceptive(model, x: np.ndarray) -> np.ndarray:
    """Return P(label == 1) for the fitted calibrated model."""
    proba = model.predict_proba(x)
    # classes_ tells us which column corresponds to the deceptive label (1).
    classes = list(getattr(model, "classes_", [0, 1]))
    if 1 in classes:
        idx = classes.index(1)
    else:
        idx = proba.shape[1] - 1
    return proba[:, idx]


def train(
    data_path: str, out_dir: str, seed: int = SEED
) -> Tuple[str, str, Dict[str, object]]:
    """Train both baselines, pick the best by PR-AUC, save artifacts.

    Returns (model_path, metrics_path, metrics_dict).
    """
    import joblib

    _seed_everything(seed)

    examples = load_examples(data_path)
    if len(examples) < 4:
        raise SystemExit(
            "Need at least 4 labeled examples to train. "
            f"Got {len(examples)} from {data_path}. "
            "Generate data first, e.g. `python -m proofml.synth --out " + data_path + "`."
        )

    x = to_matrix(examples)
    y = labels(examples)

    if len(np.unique(y)) < 2:
        raise SystemExit(
            "Training data has only one class; cannot learn a deception boundary. "
            "Generate balanced honest/deceptive rows with proofml.synth."
        )

    train_idx, test_idx = _split_indices(y, seed=seed)
    x_train, x_test = x[train_idx], x[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]

    models = _build_models(seed)
    results: Dict[str, Dict[str, object]] = {}

    for name, model in models.items():
        model.fit(x_train, y_train)
        proba = _proba_deceptive(model, x_test)
        metrics = _evaluate(y_test, proba)
        results[name] = {"model": model, "metrics": metrics}

    # Pick the winner by PR-AUC, breaking ties by ROC-AUC then lower Brier.
    def _key(item):
        m = item[1]["metrics"]
        return (m["pr_auc"], m["roc_auc"], -m["brier"])

    chosen_name, chosen = max(results.items(), key=_key)
    chosen_model = chosen["model"]
    chosen_metrics = dict(chosen["metrics"])

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model_path = out / "model.joblib"
    metrics_path = out / "metrics.json"
    heldout_path = out / "heldout.jsonl"

    joblib.dump(chosen_model, model_path)

    # Persist the exact held-out rows the model never trained on, so the cascade
    # scores its frontier on the model's genuine test set instead of guessing
    # the split. This is the source of truth for the honest frontier.
    held_examples = [examples[i] for i in test_idx]
    write_examples(held_examples, str(heldout_path))

    metrics_payload: Dict[str, object] = {
        "chosen_model": chosen_name,
        "pr_auc": chosen_metrics["pr_auc"],
        "roc_auc": chosen_metrics["roc_auc"],
        "brier": chosen_metrics["brier"],
        "precision": chosen_metrics["precision"],
        "recall": chosen_metrics["recall"],
        "f1": chosen_metrics["f1"],
        "n_examples": int(len(examples)),
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
        "n_features": int(x.shape[1]),
        "seed": int(seed),
        "candidates": {
            name: res["metrics"] for name, res in results.items()
        },
    }
    metrics_path.write_text(
        json.dumps(metrics_payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    return str(model_path), str(metrics_path), metrics_payload


def _print_summary(metrics: Dict[str, object], model_path: str, metrics_path: str) -> None:
    """Print a readable metrics summary to stdout."""
    print("proofml.train results")
    print("=" * 48)
    print(f"examples: {metrics['n_examples']}  "
          f"train: {metrics['n_train']}  test: {metrics['n_test']}  "
          f"features: {metrics['n_features']}")
    print(f"chosen model: {metrics['chosen_model']}  (best PR-AUC)")
    print("-" * 48)
    print(f"  PR-AUC    {metrics['pr_auc']:.4f}")
    print(f"  ROC-AUC   {metrics['roc_auc']:.4f}")
    print(f"  Brier     {metrics['brier']:.4f}")
    print(f"  precision {metrics['precision']:.4f}")
    print(f"  recall    {metrics['recall']:.4f}")
    print(f"  f1        {metrics['f1']:.4f}")
    print("-" * 48)
    print("candidate PR-AUC:")
    candidates = metrics.get("candidates", {})
    for name, m in candidates.items():
        marker = " <- chosen" if name == metrics["chosen_model"] else ""
        print(f"  {name:24s} {m['pr_auc']:.4f}{marker}")
    print("-" * 48)
    print(f"model:   {model_path}")
    print(f"metrics: {metrics_path}")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="proofml.train",
        description="Train calibrated deception baselines and keep the best by PR-AUC.",
    )
    parser.add_argument(
        "--data",
        default="data/examples.jsonl",
        help="Path to the examples.jsonl interchange file.",
    )
    parser.add_argument(
        "--out",
        default="artifacts",
        help="Output directory for model.joblib and metrics.json.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
        help="Random seed for full determinism.",
    )
    args = parser.parse_args(argv)

    model_path, metrics_path, metrics = train(args.data, args.out, seed=args.seed)
    _print_summary(metrics, model_path, metrics_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
