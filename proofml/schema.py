"""Canonical row schema for proofml plus the real proof ledger mapping.

The Example dataclass is the single row type every module agrees on. Behavioral
signal defaults are neutral so ledger-only rows (which carry no behavioral data)
degrade gracefully instead of leaking a fake signal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# Documents the REAL proof ledger entry shape, confirmed against
# proof/scripts/proofkit/verdict.py and ledger.py. One JSON object per line at
# ~/.proof/ledger.jsonl with these keys exactly:
#   {"project": str, "overall": "pass"|"fail"|"inconclusive",
#    "n_claims": int, "fails": [method,...], "claims": [str,...], "ts": float}
# There is NO "claim"/"verdict"/"strategy"/"timestamp" key. The values below map
# each real key to its meaning in proofml terms.
LEDGER_KEYS = {
    "claims": "claim list",
    "overall": "verdict",
    "fails": "failed method names",
    "ts": "timestamp",
    "project": "project",
}


@dataclass
class Example:
    """One labeled training row.

    label: 1 = deceptive (claim false), 0 = honest (claim true).
    label==None is not allowed here. Unlabeled rows (transcript inference) use a
    separate path that yields feature dicts, not Examples.
    """

    claim: str
    label: int
    project: str = ""
    ts: float = 0.0
    source: str = "ledger"  # one of: ledger | synth | transcript

    # behavioral signals (the real deception signal lives here, not in claim text)
    ran_test_cmd: bool = False
    claimed_without_running: bool = False
    diff_lines: int = 0
    touched_test_files: bool = False

    # claim-text signals
    hedged: bool = False
    absolute: bool = False


def from_ledger_entry(entry: dict) -> List[Example]:
    """Explode one real ledger entry into one Example per claim string.

    label = 1 if overall == "fail" else 0. Rows where overall == "inconclusive"
    are dropped (returns an empty list). Behavioral fields stay at defaults
    because the ledger carries no behavioral signal. source = "ledger".
    """
    overall = entry.get("overall")
    if overall == "inconclusive":
        return []
    label = 1 if overall == "fail" else 0
    project = entry.get("project", "") or ""
    ts = float(entry.get("ts", 0.0) or 0.0)
    claims = entry.get("claims", []) or []

    out: List[Example] = []
    for claim in claims:
        if not isinstance(claim, str):
            continue
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
