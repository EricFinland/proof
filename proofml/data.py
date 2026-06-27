"""Loading Examples from the real proof ledger and the examples.jsonl interchange.

The examples.jsonl interchange format: one JSON object per line = asdict(Example).
train, synth, extract, cascade, and benchmark all read/write this format via
load_examples / write_examples so there is a single round-trippable shape.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import List, Optional

from proofml.schema import Example, from_ledger_entry


def _ledger_path(path: Optional[str] = None) -> Path:
    """Resolve the ledger path using proof's own default logic.

    Mirrors proof/scripts/proofkit/ledger.py _path: explicit path wins, else
    PROOF_HOME env var, else ~/.proof. The file is ledger.jsonl.
    """
    if path:
        return Path(path)
    env = os.environ.get("PROOF_HOME", "")
    base = Path(env) if env else Path.home() / ".proof"
    return base / "ledger.jsonl"


def load_ledger(path: Optional[str] = None) -> List[Example]:
    """Read the proof ledger.jsonl into Examples.

    Defaults to ~/.proof/ledger.jsonl (or $PROOF_HOME/ledger.jsonl). Corrupt
    lines are skipped. Inconclusive entries are dropped (via from_ledger_entry).
    Returns an empty list if the ledger does not exist.
    """
    p = _ledger_path(path)
    if not p.exists():
        return []
    out: List[Example] = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        out.extend(from_ledger_entry(entry))
    return out


_FIELD_NAMES = {f.name for f in fields(Example)}


def _example_from_dict(obj: dict) -> Optional[Example]:
    """Build an Example from a plain dict, ignoring unknown keys.

    Returns None if the row has no usable label (label is required for Examples;
    unlabeled rows belong to the extract.py inference path, not here).
    """
    if not isinstance(obj, dict):
        return None
    if obj.get("label") is None:
        return None
    kwargs = {k: v for k, v in obj.items() if k in _FIELD_NAMES}
    if "claim" not in kwargs:
        return None
    try:
        kwargs["label"] = int(kwargs["label"])
    except (TypeError, ValueError):
        return None
    return Example(**kwargs)


def load_examples(path: str) -> List[Example]:
    """Load the examples.jsonl interchange file into Examples.

    One JSON object per line. Malformed lines and unlabeled rows are skipped.
    """
    p = Path(path)
    if not p.exists():
        return []
    out: List[Example] = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        ex = _example_from_dict(obj)
        if ex is not None:
            out.append(ex)
    return out


def write_examples(examples: List[Example], path: str) -> str:
    """Write Examples to the examples.jsonl interchange format.

    One asdict(Example) JSON object per line. Creates parent dirs. Returns the
    path written.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for ex in examples:
            fh.write(json.dumps(asdict(ex)) + "\n")
    return str(p)
