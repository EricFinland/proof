"""Tests for proofkit.ledger (M8.1)."""
import json
import os
import time
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_ledger():
    from proofkit import ledger
    return ledger


# ---------------------------------------------------------------------------
# 8.1a: append + read round-trip in a tmp root
# ---------------------------------------------------------------------------

def test_append_read_roundtrip(tmp_path):
    ledger = _import_ledger()
    entry = {"overall": "pass", "project": "myapp", "n_claims": 2, "fails": [], "claims": ["tests pass"]}
    ledger.append_entry(entry, root=str(tmp_path))

    entries = ledger.read_entries(root=str(tmp_path))
    assert len(entries) == 1
    assert entries[0]["overall"] == "pass"
    assert entries[0]["project"] == "myapp"
    # ts should have been stamped automatically
    assert "ts" in entries[0]


def test_append_preserves_existing_ts(tmp_path):
    ledger = _import_ledger()
    ts_val = 1000000.0
    entry = {"overall": "pass", "ts": ts_val}
    ledger.append_entry(entry, root=str(tmp_path))
    entries = ledger.read_entries(root=str(tmp_path))
    assert entries[0]["ts"] == ts_val


def test_multiple_entries(tmp_path):
    ledger = _import_ledger()
    for i in range(3):
        ledger.append_entry({"overall": "pass", "project": f"p{i}"}, root=str(tmp_path))
    entries = ledger.read_entries(root=str(tmp_path))
    assert len(entries) == 3


# ---------------------------------------------------------------------------
# 8.1b: corrupt line skipped silently
# ---------------------------------------------------------------------------

def test_corrupt_line_skipped(tmp_path):
    ledger = _import_ledger()
    p = ledger._path(root=str(tmp_path))
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write two good lines and one corrupt line in the middle
    p.write_text(
        '{"overall":"pass","ts":1.0}\nNOT_JSON!!!\n{"overall":"fail","ts":2.0}\n',
        encoding="utf-8",
    )
    entries = ledger.read_entries(root=str(tmp_path))
    assert len(entries) == 2
    assert entries[0]["overall"] == "pass"
    assert entries[1]["overall"] == "fail"


# ---------------------------------------------------------------------------
# 8.1c: days filter
# ---------------------------------------------------------------------------

def test_days_filter(tmp_path):
    ledger = _import_ledger()
    now = time.time()
    old_ts = now - (10 * 86400)  # 10 days ago
    recent_ts = now - (1 * 86400)  # 1 day ago
    p = ledger._path(root=str(tmp_path))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"overall": "pass", "ts": old_ts}) + "\n" +
        json.dumps({"overall": "fail", "ts": recent_ts}) + "\n",
        encoding="utf-8",
    )
    entries = ledger.read_entries(days=7, root=str(tmp_path))
    assert len(entries) == 1
    assert entries[0]["overall"] == "fail"


# ---------------------------------------------------------------------------
# 8.1d: compute_stats -- full math on 6-entry history with 2 fails
# ---------------------------------------------------------------------------

def _make_history():
    """6 entries: 4 pass, 2 fail. Last 3 are pass (streak=3). Fails have method 'tests' x2."""
    now = time.time()
    return [
        {"overall": "fail", "fails": ["tests"], "claims": ["all tests pass"], "ts": now - 500},
        {"overall": "pass", "fails": [],         "claims": ["build ok"],       "ts": now - 400},
        {"overall": "fail", "fails": ["tests", "build"], "claims": ["done"],   "ts": now - 300},
        {"overall": "pass", "fails": [],         "claims": ["deployed"],       "ts": now - 200},
        {"overall": "pass", "fails": [],         "claims": ["tests pass"],     "ts": now - 100},
        {"overall": "pass", "fails": [],         "claims": ["all good"],       "ts": now - 10},
    ]


def test_compute_stats_totals():
    ledger = _import_ledger()
    entries = _make_history()
    stats = ledger.compute_stats(entries)
    assert stats["total"] == 6
    assert stats["passes"] == 4
    assert stats["fails"] == 2
    assert stats["inconclusive"] == 0


def test_compute_stats_honesty_rate():
    ledger = _import_ledger()
    entries = _make_history()
    stats = ledger.compute_stats(entries)
    # 4 passes / (4 passes + 2 fails) = 4/6
    assert abs(stats["honesty_rate"] - 4 / 6) < 1e-9


def test_compute_stats_clean_streak():
    ledger = _import_ledger()
    entries = _make_history()
    stats = ledger.compute_stats(entries)
    # Last 3 entries are all "pass"
    assert stats["clean_streak"] == 3


def test_compute_stats_worst_method():
    ledger = _import_ledger()
    entries = _make_history()
    stats = ledger.compute_stats(entries)
    # fail entry 1 has ["tests"], fail entry 2 has ["tests","build"] -> tests:2, build:1
    assert stats["worst_method"] == "tests"


def test_compute_stats_last_catch():
    ledger = _import_ledger()
    entries = _make_history()
    stats = ledger.compute_stats(entries)
    # Most recent fail is index 2 (ts = now-300), claim "done"
    assert stats["last_catch"] is not None
    assert stats["last_catch"]["claim"] == "done"
    assert stats["last_catch"]["ts"] == entries[2]["ts"]


# ---------------------------------------------------------------------------
# 8.1e: empty entries -> sensible defaults
# ---------------------------------------------------------------------------

def test_compute_stats_empty():
    ledger = _import_ledger()
    stats = ledger.compute_stats([])
    assert stats["total"] == 0
    assert stats["passes"] == 0
    assert stats["fails"] == 0
    assert stats["inconclusive"] == 0
    assert stats["honesty_rate"] is None
    assert stats["clean_streak"] == 0
    assert stats["worst_method"] is None
    assert stats["last_catch"] is None


# ---------------------------------------------------------------------------
# 8.1f: PROOF_HOME env var respected by _path
# ---------------------------------------------------------------------------

def test_path_uses_proof_home(tmp_path, monkeypatch):
    ledger = _import_ledger()
    monkeypatch.setenv("PROOF_HOME", str(tmp_path))
    p = ledger._path()
    assert p.parent == tmp_path
    assert p.name == "ledger.jsonl"


def test_path_uses_root_over_env(tmp_path, monkeypatch):
    ledger = _import_ledger()
    other = tmp_path / "other"
    monkeypatch.setenv("PROOF_HOME", str(tmp_path))
    p = ledger._path(root=str(other))
    # explicit root wins over env
    assert str(other) in str(p)
