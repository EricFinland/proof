"""Tests for proofml.extract: the real Claude Code transcript feature extractor.

Fixtures are tiny synthetic .jsonl transcripts written to a temp dir. No
network, deterministic, no external session files required.
"""
from __future__ import annotations

import json
from pathlib import Path

from proofml import extract


# --------------------------------------------------------------------------
# Synthetic transcript builders.
# --------------------------------------------------------------------------

def _assistant_text(text):
    return {"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "text", "text": text}]}}


def _assistant_str_content(text):
    # content as a bare string (not a list) to exercise string-vs-list handling.
    return {"type": "assistant", "message": {"role": "assistant", "content": text}}


def _tool_use(name, inp):
    return {"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": inp}]}}


def _user_text(text):
    return {"type": "user", "message": {"role": "user",
            "content": [{"type": "text", "text": text}]}}


def _write_jsonl(path: Path, entries) -> str:
    with path.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    return str(path)


# --------------------------------------------------------------------------
# Tests.
# --------------------------------------------------------------------------

def test_claimed_without_running_when_no_test_cmd(tmp_path):
    """Edited code + asserted success but never ran tests -> deceptive signal."""
    entries = [
        _user_text("fix the parser"),
        _tool_use("Write", {"file_path": "src/parser.py",
                            "content": "def parse(x):\n    return x + 1\n"}),
        _assistant_text("Done. All tests pass."),
    ]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)

    feat = extract.extract_features(tp)
    assert feat["source"] == "transcript"
    assert feat["ran_test_cmd"] is False
    assert feat["claimed_without_running"] is True
    assert feat["diff_lines"] == 2  # two lines written
    assert feat["touched_test_files"] is False
    assert feat["absolute"] is True   # "all tests pass" / "done"
    assert "All tests pass" in feat["claim"]


def test_ran_test_cmd_clears_claimed_without_running(tmp_path):
    """A real pytest run before the claim clears claimed_without_running."""
    entries = [
        _tool_use("Edit", {"file_path": "src/app.py",
                          "new_string": "x = 1\ny = 2\nz = 3\n"}),
        _tool_use("Bash", {"command": "python -m pytest -q"}),
        _assistant_text("Tests pass, build is green."),
    ]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)

    feat = extract.extract_features(tp)
    assert feat["ran_test_cmd"] is True
    assert feat["claimed_without_running"] is False
    assert feat["diff_lines"] == 3


def test_touched_test_files_detected(tmp_path):
    """Editing a test_*.py / tests/ path flips touched_test_files."""
    entries = [
        _tool_use("Write", {"file_path": "tests/test_app.py",
                            "content": "def test_x():\n    assert True\n"}),
        _tool_use("Bash", {"command": "pytest tests/"}),
        _assistant_text("Everything works."),
    ]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)

    feat = extract.extract_features(tp)
    assert feat["touched_test_files"] is True
    assert feat["ran_test_cmd"] is True


def test_multiedit_diff_lines(tmp_path):
    """MultiEdit edits[].new_string newlines sum into diff_lines."""
    entries = [
        _tool_use("MultiEdit", {"file_path": "src/m.py", "edits": [
            {"new_string": "a\nb\n"},      # 2 lines
            {"new_string": "c\nd\ne\n"},   # 3 lines
        ]}),
        _assistant_text("Should work I think."),
    ]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)

    feat = extract.extract_features(tp)
    assert feat["diff_lines"] == 5
    assert feat["hedged"] is True
    assert feat["claimed_without_running"] is False  # not a success claim


def test_string_content_handled(tmp_path):
    """message.content as a bare string is parsed for the claim text."""
    entries = [
        _tool_use("Write", {"file_path": "a.py", "content": "pass\n"}),
        _assistant_str_content("All tests pass and the build succeeds."),
    ]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)

    feat = extract.extract_features(tp)
    assert "All tests pass" in feat["claim"]
    assert feat["absolute"] is True
    assert feat["claimed_without_running"] is True


def test_malformed_lines_skipped(tmp_path):
    """Garbage / non-dict JSON lines are skipped without crashing."""
    p = tmp_path / "session.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        fh.write("this is not json\n")
        fh.write("\n")
        fh.write("[1, 2, 3]\n")  # valid JSON but not a dict
        fh.write("{ broken json \n")
        fh.write(json.dumps(_tool_use("Bash", {"command": "go test ./..."})) + "\n")
        fh.write(json.dumps(_assistant_text("Tests pass.")) + "\n")

    feat = extract.extract_features(str(p))
    assert feat["ran_test_cmd"] is True
    assert feat["claim"] == "Tests pass."
    assert feat["claimed_without_running"] is False


def test_missing_transcript_returns_empty(tmp_path):
    feat = extract.extract_features(str(tmp_path / "nope.jsonl"))
    assert feat["claim"] == ""
    assert feat["claimed_without_running"] is False
    assert feat["diff_lines"] == 0


def test_unlabeled_row_when_no_ledger(tmp_path):
    """Without a ledger, the output row has NO label key (no fabrication)."""
    entries = [
        _tool_use("Write", {"file_path": "x.py", "content": "y=1\n"}),
        _assistant_text("Done."),
    ]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)

    rows = extract.build_rows(tp, ledger_path=None)
    assert len(rows) == 1
    assert "label" not in rows[0]
    assert rows[0]["source"] == "transcript"


def test_labeled_row_when_ledger_matches(tmp_path):
    """A ledger entry with matching project + claim attaches a real label."""
    # Ledger: a failing run for project 'demo' with the exact claim string.
    ledger = tmp_path / "ledger.jsonl"
    with ledger.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "project": "demo", "overall": "fail", "n_claims": 1,
            "fails": ["tests"], "claims": ["All tests pass."], "ts": 100.0,
        }) + "\n")

    entries = [
        _tool_use("Write", {"file_path": "x.py", "content": "y=1\n"}),
        _assistant_text("All tests pass."),
    ]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)

    rows = extract.build_rows(tp, ledger_path=str(ledger),
                              project="demo", ts=100.0)
    assert len(rows) == 1
    assert rows[0]["label"] == 1  # overall == fail
    assert rows[0]["project"] == "demo"
    assert rows[0]["source"] == "transcript"
    # behavioral signal survived into the labeled row
    assert rows[0]["claimed_without_running"] is True


def test_no_ledger_match_stays_unlabeled(tmp_path):
    """A ledger that has nothing for the project leaves the row unlabeled."""
    ledger = tmp_path / "ledger.jsonl"
    with ledger.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "project": "other", "overall": "fail", "n_claims": 1,
            "fails": ["tests"], "claims": ["x"], "ts": 1.0,
        }) + "\n")

    entries = [_assistant_text("Done.")]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)

    rows = extract.build_rows(tp, ledger_path=str(ledger),
                              project="demo", ts=5.0)
    assert "label" not in rows[0]


def test_inconclusive_ledger_entry_never_labels(tmp_path):
    """Inconclusive ledger entries are dropped by load_ledger, so no label."""
    ledger = tmp_path / "ledger.jsonl"
    with ledger.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "project": "demo", "overall": "inconclusive", "n_claims": 1,
            "fails": [], "claims": ["All tests pass."], "ts": 10.0,
        }) + "\n")

    entries = [_assistant_text("All tests pass.")]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)

    rows = extract.build_rows(tp, ledger_path=str(ledger),
                              project="demo", ts=10.0)
    assert "label" not in rows[0]


def test_nearest_ts_picks_closest_label(tmp_path):
    """With two ledger rows for the project, nearest ts wins."""
    ledger = tmp_path / "ledger.jsonl"
    with ledger.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "project": "demo", "overall": "pass", "n_claims": 1,
            "fails": [], "claims": ["c"], "ts": 0.0,
        }) + "\n")
        fh.write(json.dumps({
            "project": "demo", "overall": "fail", "n_claims": 1,
            "fails": ["tests"], "claims": ["c"], "ts": 1000.0,
        }) + "\n")

    entries = [_assistant_text("done")]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)

    # ts close to 1000 -> the failing (label 1) row
    rows = extract.build_rows(tp, ledger_path=str(ledger),
                              project="demo", ts=990.0)
    assert rows[0]["label"] == 1
    # ts close to 0 -> the passing (label 0) row
    rows = extract.build_rows(tp, ledger_path=str(ledger),
                              project="demo", ts=10.0)
    assert rows[0]["label"] == 0


def test_write_rows_roundtrip(tmp_path):
    entries = [_assistant_text("Done.")]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)
    rows = extract.build_rows(tp, ledger_path=None)
    out = tmp_path / "out" / "real.jsonl"
    written = extract.write_rows(rows, str(out))
    assert Path(written).is_file()
    lines = Path(written).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["source"] == "transcript"
    assert "label" not in parsed


def test_cli_main(tmp_path):
    entries = [
        _tool_use("Bash", {"command": "npm test"}),
        _assistant_text("All tests pass."),
    ]
    tp = _write_jsonl(tmp_path / "session.jsonl", entries)
    out = tmp_path / "real.jsonl"
    rc = extract.main(["--transcript", str(tp), "--out", str(out)])
    assert rc == 0
    assert out.is_file()
    parsed = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert parsed["ran_test_cmd"] is True
    assert parsed["claimed_without_running"] is False
