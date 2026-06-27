"""proofbench: freeze a versioned benchmark set and score a model against it.

Two subcommands:

  freeze  Reads an examples.jsonl interchange file, writes a versioned frozen
          benchmark set (one asdict(Example) per line) plus a sidecar
          <out>.meta.json recording a sha256 checksum of the frozen file, the
          row count, the label balance, and the category counts. Freezing makes
          the benchmark reproducible: the checksum lets a reviewer confirm the
          exact bytes scored later were not silently changed.

  score   Loads a fitted calibrated model (artifacts/model.joblib from train.py)
          and scores it against a frozen benchmark, broken down per category:
          absolute claims vs hedged claims. Prints per-category accuracy and
          PR-AUC plus an overall leaderboard line.

Featurization goes through proofml.features.to_matrix so train, cascade, and
benchmark all share exactly one feature path.

Usage:
  python -m proofml.benchmark freeze --data data/examples.jsonl \
      --out bench/proofbench_v1.jsonl
  python -m proofml.benchmark score --bench bench/proofbench_v1.jsonl \
      --model artifacts/model.joblib
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from proofml.data import load_examples, write_examples
from proofml.features import labels, to_matrix
from proofml.schema import Example

# Version stamp recorded into the .meta.json sidecar. Bump when the freeze
# format or the category definitions change.
BENCH_VERSION = "v1"

# Category names used by score. A row can fall into more than one category band
# (a claim may be both absolute and hedged, or neither), so categories overlap
# rather than partition. "overall" always covers every row.
CAT_ABSOLUTE = "absolute"
CAT_HEDGED = "hedged"
CAT_OVERALL = "overall"


def sha256_file(path: str) -> str:
    """Return the hex sha256 of a file read in binary chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _label_balance(examples: List[Example]) -> Dict[str, int]:
    deceptive = sum(1 for e in examples if int(e.label) == 1)
    honest = sum(1 for e in examples if int(e.label) == 0)
    return {"deceptive": deceptive, "honest": honest}


def _category_counts(examples: List[Example]) -> Dict[str, int]:
    return {
        CAT_ABSOLUTE: sum(1 for e in examples if e.absolute),
        CAT_HEDGED: sum(1 for e in examples if e.hedged),
        CAT_OVERALL: len(examples),
    }


def meta_path_for(out_path: str) -> str:
    """Return the .meta.json sidecar path for a frozen benchmark path.

    bench/proofbench_v1.jsonl -> bench/proofbench_v1.meta.json. A trailing
    .jsonl is replaced; otherwise .meta.json is appended.
    """
    p = Path(out_path)
    if p.suffix == ".jsonl":
        return str(p.with_suffix(".meta.json"))
    return str(p) + ".meta.json"


def freeze(data_path: str, out_path: str) -> Dict[str, object]:
    """Freeze examples.jsonl into a checksummed versioned benchmark set.

    Reads labeled Examples from data_path, writes them verbatim (one
    asdict(Example) per line) to out_path, then writes <out>.meta.json with a
    sha256 of the frozen file and summary stats. Returns the meta dict.
    """
    examples = load_examples(data_path)
    if not examples:
        raise SystemExit(
            "freeze: no labeled examples found in %s (need labeled rows)" % data_path
        )

    written = write_examples(examples, out_path)
    checksum = sha256_file(written)

    meta = {
        "version": BENCH_VERSION,
        "source": str(data_path),
        "bench_file": str(written),
        "sha256": checksum,
        "n_rows": len(examples),
        "label_balance": _label_balance(examples),
        "categories": _category_counts(examples),
        "feature_path": "proofml.features.to_matrix",
    }

    mpath = meta_path_for(out_path)
    Path(mpath).parent.mkdir(parents=True, exist_ok=True)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
        fh.write("\n")

    print("froze %d rows -> %s" % (len(examples), written))
    print("  sha256: %s" % checksum)
    print(
        "  balance: %d deceptive / %d honest"
        % (meta["label_balance"]["deceptive"], meta["label_balance"]["honest"])
    )
    print(
        "  categories: %d absolute, %d hedged"
        % (meta["categories"][CAT_ABSOLUTE], meta["categories"][CAT_HEDGED])
    )
    print("  meta: %s" % mpath)
    return meta


def verify_checksum(bench_path: str) -> Optional[bool]:
    """If a sidecar meta with a sha256 exists, check the frozen file matches it.

    Returns True if matched, False if mismatched, None if no meta/checksum was
    found. score uses this to warn (not fail) on a tampered benchmark.
    """
    mpath = Path(meta_path_for(bench_path))
    if not mpath.exists():
        return None
    try:
        meta = json.loads(mpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    expected = meta.get("sha256")
    if not expected:
        return None
    return sha256_file(bench_path) == expected


def _safe_pr_auc(y_true, scores) -> float:
    """Average-precision (PR-AUC). Returns nan when only one class is present."""
    import numpy as np
    from sklearn.metrics import average_precision_score

    y = np.asarray(y_true, dtype=int)
    if y.size == 0 or len(set(y.tolist())) < 2:
        return float("nan")
    return float(average_precision_score(y, scores))


def _accuracy(y_true, scores, threshold: float = 0.5) -> float:
    import numpy as np

    y = np.asarray(y_true, dtype=int)
    if y.size == 0:
        return float("nan")
    preds = (np.asarray(scores, dtype=float) >= threshold).astype(int)
    return float((preds == y).mean())


def _deceptive_scores(model, examples: List[Example]):
    """Return predict_proba for the deceptive class (label 1) over examples.

    The deceptive column is located via model.classes_ when available so we do
    not assume column ordering. Falls back to column 1 of a 2-class output.
    """
    import numpy as np

    X = to_matrix(examples)
    proba = model.predict_proba(X)
    proba = np.asarray(proba, dtype=float)
    classes = getattr(model, "classes_", None)
    if classes is not None:
        classes = list(classes)
        if 1 in classes:
            return proba[:, classes.index(1)]
    # Fallback: standard 2-class layout puts the positive class last.
    if proba.ndim == 2 and proba.shape[1] >= 2:
        return proba[:, 1]
    return proba.ravel()


def _score_subset(
    model, examples: List[Example]
) -> Tuple[float, float, int]:
    """Return (accuracy, pr_auc, n) for a subset of examples."""
    n = len(examples)
    if n == 0:
        return float("nan"), float("nan"), 0
    scores = _deceptive_scores(model, examples)
    y = labels(examples)
    acc = _accuracy(y, scores)
    pr = _safe_pr_auc(y, scores)
    return acc, pr, n


def score(bench_path: str, model_path: str) -> Dict[str, object]:
    """Score a model against a frozen benchmark, broken down per category.

    Categories scored: absolute claims, hedged claims, and overall. Prints
    per-category accuracy and PR-AUC plus a one-line leaderboard summary.
    Returns a results dict.
    """
    examples = load_examples(bench_path)
    if not examples:
        raise SystemExit("score: no labeled examples found in %s" % bench_path)

    if not Path(model_path).exists():
        raise SystemExit("score: model not found at %s (run proofml.train first)" % model_path)

    checksum_ok = verify_checksum(bench_path)
    if checksum_ok is False:
        print(
            "WARNING: benchmark sha256 does not match its .meta.json "
            "(the frozen file changed since freeze)",
            file=sys.stderr,
        )

    import joblib

    model = joblib.load(model_path)

    subsets = {
        CAT_ABSOLUTE: [e for e in examples if e.absolute],
        CAT_HEDGED: [e for e in examples if e.hedged],
        CAT_OVERALL: examples,
    }

    results: Dict[str, object] = {
        "bench_file": str(bench_path),
        "model": str(model_path),
        "checksum_ok": checksum_ok,
        "categories": {},
    }

    print("proofbench score: %s vs %s" % (model_path, bench_path))
    if checksum_ok is True:
        print("  checksum: OK")
    elif checksum_ok is None:
        print("  checksum: no meta sidecar found")
    print("  %-10s %8s %8s %6s" % ("category", "acc", "pr_auc", "n"))
    for cat in (CAT_ABSOLUTE, CAT_HEDGED, CAT_OVERALL):
        acc, pr, n = _score_subset(model, subsets[cat])
        results["categories"][cat] = {"accuracy": acc, "pr_auc": pr, "n": n}
        print("  %-10s %8.3f %8.3f %6d" % (cat, acc, pr, n))

    overall = results["categories"][CAT_OVERALL]
    print(
        "LEADERBOARD  proofbench_%s  acc=%.3f  pr_auc=%.3f  n=%d  "
        "(absolute pr_auc=%.3f, hedged pr_auc=%.3f)"
        % (
            BENCH_VERSION,
            overall["accuracy"],
            overall["pr_auc"],
            overall["n"],
            results["categories"][CAT_ABSOLUTE]["pr_auc"],
            results["categories"][CAT_HEDGED]["pr_auc"],
        )
    )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m proofml.benchmark",
        description="Freeze and score the proofbench deception benchmark.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_freeze = sub.add_parser(
        "freeze", help="write a versioned sha256-checksummed frozen benchmark set"
    )
    p_freeze.add_argument(
        "--data", required=True, help="input examples.jsonl interchange file"
    )
    p_freeze.add_argument(
        "--out", required=True, help="output frozen benchmark jsonl path"
    )

    p_score = sub.add_parser(
        "score", help="score a model per category against a frozen benchmark"
    )
    p_score.add_argument(
        "--bench", required=True, help="frozen benchmark jsonl path"
    )
    p_score.add_argument(
        "--model", required=True, help="path to model.joblib from proofml.train"
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "freeze":
        freeze(args.data, args.out)
    elif args.cmd == "score":
        score(args.bench, args.model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
