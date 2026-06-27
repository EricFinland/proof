"""Turn the enriched proof ledger into training data and measure live accuracy.

The enriched ledger (one JSON object per line, written by proof when shadow mode
is on) carries the real verdict per session plus, optionally, the raw behavioral
signals and the shadow prediction that was made BEFORE the verifier ran. That
makes it a live, self-labeling dataset:

  - label = 1 if overall == "fail" (the claim was deceptive), else 0 for "pass".
    "inconclusive" entries are dropped.
  - behavioral signals come from the entry's "behavior" dict when present
    (these are the rich "featured" rows). Entries with no behavior are THIN:
    the behavioral fields stay at neutral defaults and source = "ledger". Thin
    rows are only emitted with --include-thin.
  - shadow_proba is the prediction the model made at the time; comparing it to
    the eventual label tells us how well shadow predictions matched reality.

Subcommands:
    python -m proofml.dataset build  --ledger <ledger.jsonl> --out data/real.jsonl [--include-thin]
    python -m proofml.dataset report --ledger <ledger.jsonl>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from proofml.data import _ledger_path, write_examples
from proofml.schema import Example


# Behavior keys carried in an enriched ledger entry's "behavior" dict.
_BEHAVIOR_KEYS = (
    "ran_test_cmd",
    "claimed_without_running",
    "diff_lines",
    "touched_test_files",
    "hedged",
    "absolute",
)


def _read_ledger_entries(ledger_path: Optional[str]) -> List[dict]:
    """Read raw ledger entry dicts (NOT exploded Examples), skipping junk.

    Uses proofml.data's default-path logic when no explicit path is given.
    """
    p = _ledger_path(ledger_path)
    if not p.exists():
        return []
    out: List[dict] = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _label_for(overall: Any) -> Optional[int]:
    """1 for fail, 0 for pass, None for anything else (e.g. inconclusive)."""
    if overall == "fail":
        return 1
    if overall == "pass":
        return 0
    return None


def entry_to_examples(entry: dict, include_thin: bool = False) -> List[Example]:
    """Explode one enriched ledger entry into Examples (one per claim string).

    Featured rows (entry has a usable "behavior" dict) carry the raw behavioral
    signals and source = "transcript". Thin rows (no behavior) carry neutral
    defaults and source = "ledger"; they are only produced when include_thin.
    """
    label = _label_for(entry.get("overall"))
    if label is None:
        return []

    project = entry.get("project", "") or ""
    ts = float(entry.get("ts", 0.0) or 0.0)
    claims = entry.get("claims", []) or []

    behavior = entry.get("behavior")
    has_behavior = isinstance(behavior, dict)
    if not has_behavior and not include_thin:
        return []

    out: List[Example] = []
    for claim in claims:
        if not isinstance(claim, str):
            continue
        if has_behavior:
            out.append(
                Example(
                    claim=claim,
                    label=label,
                    project=project,
                    ts=ts,
                    source="transcript",
                    ran_test_cmd=bool(behavior.get("ran_test_cmd", False)),
                    claimed_without_running=bool(
                        behavior.get("claimed_without_running", False)
                    ),
                    diff_lines=int(behavior.get("diff_lines", 0) or 0),
                    touched_test_files=bool(
                        behavior.get("touched_test_files", False)
                    ),
                    hedged=bool(behavior.get("hedged", False)),
                    absolute=bool(behavior.get("absolute", False)),
                )
            )
        else:
            out.append(
                Example(
                    claim=claim,
                    label=label,
                    project=project,
                    ts=ts,
                    source="ledger",
                )
            )
    return out


def build(ledger_path: Optional[str], out_path: str, include_thin: bool = False) -> Dict[str, int]:
    """Build an examples.jsonl from the enriched ledger. Returns count summary."""
    entries = _read_ledger_entries(ledger_path)

    examples: List[Example] = []
    n_featured = 0
    n_thin = 0
    for entry in entries:
        exs = entry_to_examples(entry, include_thin=include_thin)
        for ex in exs:
            if ex.source == "transcript":
                n_featured += 1
            else:
                n_thin += 1
        examples.extend(exs)

    write_examples(examples, out_path)

    n_pos = sum(1 for e in examples if e.label == 1)
    n_neg = len(examples) - n_pos
    return {
        "total": len(examples),
        "featured": n_featured,
        "thin": n_thin,
        "label_pos": n_pos,
        "label_neg": n_neg,
    }


def _collect_eval_rows(entries: List[dict]) -> List[Tuple[int, float]]:
    """(label, shadow_proba) pairs for entries with both fields usable."""
    rows: List[Tuple[int, float]] = []
    for entry in entries:
        label = _label_for(entry.get("overall"))
        if label is None:
            continue
        proba = entry.get("shadow_proba")
        if proba is None:
            continue
        try:
            rows.append((int(label), float(proba)))
        except (TypeError, ValueError):
            continue
    return rows


def _calibration_table(rows: List[Tuple[int, float]], n_buckets: int = 5) -> List[Dict[str, Any]]:
    """Bucket predictions into [0,1] bins; report mean predicted vs observed."""
    buckets: List[Dict[str, Any]] = []
    for b in range(n_buckets):
        lo = b / n_buckets
        hi = (b + 1) / n_buckets
        in_bucket = [
            (y, p) for (y, p) in rows
            if (p >= lo and (p < hi or (b == n_buckets - 1 and p <= hi)))
        ]
        if in_bucket:
            mean_pred = sum(p for _, p in in_bucket) / len(in_bucket)
            observed = sum(y for y, _ in in_bucket) / len(in_bucket)
        else:
            mean_pred = float("nan")
            observed = float("nan")
        buckets.append({
            "range": (lo, hi),
            "n": len(in_bucket),
            "mean_pred": mean_pred,
            "observed": observed,
        })
    return buckets


def report(ledger_path: Optional[str]) -> int:
    """Print LIVE PR-AUC / Brier / accuracy@0.5 + calibration. Returns exit code."""
    entries = _read_ledger_entries(ledger_path)
    rows = _collect_eval_rows(entries)

    if len(rows) < 2:
        print("not enough data: need at least 2 entries with both shadow_proba "
              "and a pass/fail verdict (have %d)." % len(rows))
        return 0

    labels_present = {y for y, _ in rows}
    single_class = len(labels_present) < 2

    y_true = [y for y, _ in rows]
    y_score = [p for _, p in rows]

    # accuracy@0.5 and Brier never need sklearn.
    correct = sum(1 for (y, p) in rows if int(p >= 0.5) == y)
    accuracy = correct / len(rows)
    brier = sum((p - y) ** 2 for (y, p) in rows) / len(rows)

    pr_auc: Optional[float] = None
    pr_auc_note = ""
    if single_class:
        pr_auc_note = "(PR-AUC skipped: only one verdict class present)"
    else:
        try:
            from sklearn.metrics import average_precision_score

            pr_auc = float(average_precision_score(y_true, y_score))
        except Exception:
            pr_auc_note = "(PR-AUC skipped: scikit-learn not available)"

    print("proofml.dataset report -- live shadow accuracy")
    print("=" * 52)
    print("rows (shadow_proba + verdict): %d" % len(rows))
    print("label balance: %d deceptive / %d honest"
          % (sum(y_true), len(y_true) - sum(y_true)))
    print("-" * 52)
    if pr_auc is not None:
        print("  PR-AUC          %.4f" % pr_auc)
    else:
        print("  PR-AUC          n/a %s" % pr_auc_note)
    print("  Brier           %.4f" % brier)
    print("  accuracy@0.5    %.4f" % accuracy)
    print("-" * 52)
    print("calibration (predicted vs observed deceptive-rate):")
    print("  %-12s %5s %12s %12s" % ("bucket", "n", "mean_pred", "observed"))
    for b in _calibration_table(rows):
        lo, hi = b["range"]
        if b["n"]:
            print("  [%.1f,%.1f)   %5d %12.4f %12.4f"
                  % (lo, hi, b["n"], b["mean_pred"], b["observed"]))
        else:
            print("  [%.1f,%.1f)   %5d %12s %12s" % (lo, hi, 0, "-", "-"))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m proofml.dataset",
        description="Build training data from the enriched proof ledger and "
        "measure live shadow-prediction accuracy.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="Build examples.jsonl from the ledger.")
    p_build.add_argument("--ledger", default=None,
                         help="Path to the enriched ledger.jsonl "
                              "(default: $PROOF_HOME/ledger.jsonl or ~/.proof/ledger.jsonl).")
    p_build.add_argument("--out", required=True, help="Output examples.jsonl path.")
    p_build.add_argument("--include-thin", action="store_true",
                         help="Also emit thin rows (no behavior dict) with defaults.")

    p_report = sub.add_parser("report", help="Live shadow-prediction accuracy.")
    p_report.add_argument("--ledger", default=None,
                          help="Path to the enriched ledger.jsonl "
                               "(default: $PROOF_HOME/ledger.jsonl or ~/.proof/ledger.jsonl).")

    args = parser.parse_args(argv)

    if args.cmd == "build":
        summary = build(args.ledger, args.out, include_thin=args.include_thin)
        print("wrote %d example(s) to %s" % (summary["total"], args.out))
        print("  featured (with behavior): %d" % summary["featured"])
        print("  thin (ledger defaults):   %d" % summary["thin"])
        print("  label balance: %d deceptive / %d honest"
              % (summary["label_pos"], summary["label_neg"]))
        return 0

    if args.cmd == "report":
        return report(args.ledger)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
