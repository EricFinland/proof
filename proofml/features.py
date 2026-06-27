"""Interpretable feature extraction shared by train, cascade, and benchmark.

No transformer, no torch. Every behavioral feature is 0 for ledger-only rows,
which is correct and intended: the ledger carries no behavioral signal.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List

import numpy as np

from proofml.schema import Example


# Stable, ordered feature names. The order defines the column order of to_matrix.
FEATURE_NAMES: List[str] = [
    "claimed_without_running",  # top signal
    "ran_test_cmd",
    "diff_lines_log",
    "touched_test_files",
    "hedged",
    "absolute",
    "claim_len",
    "n_test_words",
]


# Tokens that signal a verifiable claim about tests/build/passing.
_TEST_WORD_RE = re.compile(
    r"\b(test|tests|pass|passes|passed|passing|build|builds|building|green|"
    r"check|checks|lint|typecheck)\b",
    re.I,
)


def _n_test_words(claim: str) -> float:
    return float(len(_TEST_WORD_RE.findall(claim or "")))


def featurize(ex: Example) -> Dict[str, float]:
    """Map one Example to a dict of named features (keys == FEATURE_NAMES)."""
    claim = ex.claim or ""
    diff = ex.diff_lines if ex.diff_lines and ex.diff_lines > 0 else 0
    feats = {
        "claimed_without_running": 1.0 if ex.claimed_without_running else 0.0,
        "ran_test_cmd": 1.0 if ex.ran_test_cmd else 0.0,
        "diff_lines_log": float(math.log1p(diff)),
        "touched_test_files": 1.0 if ex.touched_test_files else 0.0,
        "hedged": 1.0 if ex.hedged else 0.0,
        "absolute": 1.0 if ex.absolute else 0.0,
        "claim_len": float(len(claim)),
        "n_test_words": _n_test_words(claim),
    }
    return {name: feats[name] for name in FEATURE_NAMES}


def to_matrix(examples: List[Example]) -> np.ndarray:
    """Stack featurize() over examples into an (n, len(FEATURE_NAMES)) array."""
    if not examples:
        return np.empty((0, len(FEATURE_NAMES)), dtype=float)
    rows = []
    for ex in examples:
        f = featurize(ex)
        rows.append([f[name] for name in FEATURE_NAMES])
    return np.asarray(rows, dtype=float)


def labels(examples: List[Example]) -> np.ndarray:
    """Return the (n,) integer label vector (1 = deceptive, 0 = honest)."""
    return np.asarray([int(ex.label) for ex in examples], dtype=int)
