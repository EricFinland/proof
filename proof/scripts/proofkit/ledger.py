"""Honesty ledger: persists verification outcomes and computes stats."""
import json
import os
import time
from collections import Counter
from pathlib import Path


def _path(root=None):
    """Return Path to ledger.jsonl, creating parent dirs as needed."""
    if root:
        base = Path(root)
    else:
        env = os.environ.get("PROOF_HOME", "")
        base = Path(env) if env else Path.home() / ".proof"
    p = base / "ledger.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append_entry(entry: dict, root=None):
    """Stamp 'ts' if absent, then append one JSON line (utf-8)."""
    entry = dict(entry)
    if "ts" not in entry:
        entry["ts"] = time.time()
    with _path(root).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def read_entries(days=None, root=None) -> list:
    """Read all ledger entries; skip corrupt lines. Filter by days if given."""
    p = _path(root)
    if not p.exists():
        return []
    cutoff = (time.time() - days * 86400) if days is not None else None
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if cutoff is not None:
            ts = obj.get("ts", 0)
            if ts < cutoff:
                continue
        entries.append(obj)
    return entries


def compute_stats(entries: list) -> dict:
    """Compute aggregate statistics over a list of entry dicts."""
    total = len(entries)
    passes = sum(1 for e in entries if e.get("overall") == "pass")
    fails = sum(1 for e in entries if e.get("overall") == "fail")
    inconclusive = total - passes - fails

    if passes + fails == 0:
        honesty_rate = None
    else:
        honesty_rate = passes / (passes + fails)

    # Clean streak: count consecutive trailing entries with overall == "pass"
    clean_streak = 0
    for e in reversed(entries):
        if e.get("overall") == "pass":
            clean_streak += 1
        else:
            break

    # Worst method: most frequent method across all fail entries' "fails" lists
    method_counts: Counter = Counter()
    for e in entries:
        if e.get("overall") == "fail":
            for m in e.get("fails", []):
                method_counts[m] += 1
    worst_method = method_counts.most_common(1)[0][0] if method_counts else None

    # Last catch: most recent overall=="fail" entry
    last_catch = None
    for e in reversed(entries):
        if e.get("overall") == "fail":
            claims = e.get("claims", [])
            claim_text = claims[0] if claims else ""
            last_catch = {"claim": claim_text, "ts": e.get("ts", 0)}
            break

    return {
        "total": total,
        "passes": passes,
        "fails": fails,
        "inconclusive": inconclusive,
        "honesty_rate": honesty_rate,
        "clean_streak": clean_streak,
        "worst_method": worst_method,
        "last_catch": last_catch,
    }
