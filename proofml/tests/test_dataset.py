"""Tests for proofml.dataset: build + report over a tiny enriched ledger."""
from __future__ import annotations

import json
from pathlib import Path

from proofml import dataset
from proofml.data import load_examples


def _write_ledger(path: Path, entries) -> str:
    with path.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    return str(path)


def _entry(overall, claims, behavior=None, shadow_proba=None, ts=1.0, project="p"):
    e = {
        "project": project,
        "overall": overall,
        "n_claims": len(claims),
        "fails": [] if overall != "fail" else ["tests"],
        "claims": claims,
        "ts": ts,
    }
    if behavior is not None:
        e["behavior"] = behavior
    if shadow_proba is not None:
        e["shadow_proba"] = shadow_proba
        e["shadow_model"] = "logistic_regression"
        e["shadow_source"] = "transcript"
    return e


_BEH_DECEPTIVE = {
    "ran_test_cmd": False, "claimed_without_running": True, "diff_lines": 30,
    "touched_test_files": False, "hedged": False, "absolute": True,
}
_BEH_HONEST = {
    "ran_test_cmd": True, "claimed_without_running": False, "diff_lines": 4,
    "touched_test_files": True, "hedged": False, "absolute": False,
}


def test_build_featured_only(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        _entry("fail", ["all tests pass"], behavior=_BEH_DECEPTIVE),
        _entry("pass", ["tests pass"], behavior=_BEH_HONEST),
        _entry("pass", ["thin claim"]),                 # thin, dropped without flag
        _entry("inconclusive", ["no claims"], behavior=_BEH_HONEST),  # dropped
    ])
    out = tmp_path / "real.jsonl"
    summary = dataset.build(str(ledger), str(out), include_thin=False)

    assert summary["featured"] == 2
    assert summary["thin"] == 0
    assert summary["total"] == 2
    assert summary["label_pos"] == 1
    assert summary["label_neg"] == 1

    exs = load_examples(str(out))
    assert len(exs) == 2
    fail_ex = [e for e in exs if e.label == 1][0]
    assert fail_ex.source == "transcript"
    assert fail_ex.claimed_without_running is True
    assert fail_ex.diff_lines == 30


def test_build_include_thin(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        _entry("fail", ["all tests pass"], behavior=_BEH_DECEPTIVE),
        _entry("pass", ["thin claim a", "thin claim b"]),  # 2 thin rows
    ])
    out = tmp_path / "real.jsonl"
    summary = dataset.build(str(ledger), str(out), include_thin=True)

    assert summary["featured"] == 1
    assert summary["thin"] == 2
    assert summary["total"] == 3

    exs = load_examples(str(out))
    thin = [e for e in exs if e.source == "ledger"]
    assert len(thin) == 2
    assert all(t.diff_lines == 0 and t.ran_test_cmd is False for t in thin)


def test_report_not_enough_data(tmp_path, capsys):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        _entry("pass", ["tests pass"], shadow_proba=0.2),  # only 1 usable row
        _entry("fail", ["all tests pass"]),                # no shadow_proba
    ])
    code = dataset.report(str(ledger))
    assert code == 0
    assert "not enough data" in capsys.readouterr().out.lower()


def test_report_with_data(tmp_path, capsys):
    ledger = tmp_path / "ledger.jsonl"
    entries = []
    # honest entries the model scored low.
    for _ in range(4):
        entries.append(_entry("pass", ["tests pass"], shadow_proba=0.1))
    # deceptive entries the model scored high.
    for _ in range(4):
        entries.append(_entry("fail", ["all tests pass"], shadow_proba=0.9))
    _write_ledger(ledger, entries)

    code = dataset.report(str(ledger))
    assert code == 0
    out = capsys.readouterr().out
    assert "Brier" in out
    assert "accuracy@0.5" in out
    assert "calibration" in out
    # Perfect separation -> accuracy 1.0
    assert "accuracy@0.5    1.0000" in out


def test_report_single_class_skips_pr_auc(tmp_path, capsys):
    ledger = tmp_path / "ledger.jsonl"
    entries = [_entry("pass", ["tests pass"], shadow_proba=0.1) for _ in range(3)]
    _write_ledger(ledger, entries)
    code = dataset.report(str(ledger))
    assert code == 0
    out = capsys.readouterr().out
    assert "PR-AUC" in out  # printed, but as n/a


# --- gate subcommand ---------------------------------------------------------


def _write_gate(path: Path, decisions) -> str:
    with path.open("w", encoding="utf-8") as fh:
        for d in decisions:
            fh.write(json.dumps(d) + "\n")
    return str(path)


def _gate(decision, proba, claim="all tests pass", ts=1.0, project="p"):
    return {
        "ts": ts, "project": project, "session": "s1", "claim": claim,
        "proba": proba, "threshold": 0.5, "audit_rate": 0.1,
        "decision": decision, "source": "transcript", "behavior": None,
    }


def test_gate_report_missing_file(tmp_path, capsys):
    code = dataset.gate_report(str(tmp_path / "nope.jsonl"), None)
    assert code == 0
    assert "no gate decisions" in capsys.readouterr().out.lower()


def test_gate_report_skip_rate(tmp_path, capsys):
    gate = tmp_path / "gate.jsonl"
    decisions = []
    for _ in range(6):
        decisions.append(_gate("skip", 0.05))
    for _ in range(3):
        decisions.append(_gate("verify", 0.9))
    decisions.append(_gate("audit", 0.05))
    _write_gate(gate, decisions)

    code = dataset.gate_report(str(gate), None)
    assert code == 0
    out = capsys.readouterr().out
    assert "total decisions: 10" in out
    # skip rate = 6 / 10
    assert "SKIP RATE" in out
    assert "0.6000" in out
    # no ledger -> miss rate n/a
    assert "audit-slice miss rate: n/a" in out.lower()


def test_gate_report_audit_miss_rate(tmp_path, capsys):
    gate = tmp_path / "gate.jsonl"
    # Two audited claims, both predicted honest. Distinct claim text per ts so the
    # ledger join is unambiguous.
    decisions = [
        _gate("skip", 0.02, claim="honest claim a", ts=100.0),
        _gate("audit", 0.03, claim="audited liar", ts=200.0),
        _gate("audit", 0.04, claim="audited honest", ts=300.0),
        _gate("verify", 0.8, claim="risky claim", ts=400.0),
    ]
    _write_gate(gate, decisions)

    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        _entry("fail", ["audited liar"], ts=201.0),     # audited -> turned out FAIL (a miss)
        _entry("pass", ["audited honest"], ts=301.0),   # audited -> passed (not a miss)
    ])

    code = dataset.gate_report(str(gate), str(ledger))
    assert code == 0
    out = capsys.readouterr().out
    assert "joined to a verdict     : 2" in out
    assert "turned out FAIL (misses): 1" in out
    # miss rate = 1 / 2
    assert "0.5000" in out


def test_suspect_entries_are_labeled_deceptive(tmp_path):
    assert dataset._label_for("suspect") == 1
    assert dataset._label_for("fail") == 1
    assert dataset._label_for("pass") == 0
    assert dataset._label_for("inconclusive") is None
    rows = dataset.entry_to_examples(_entry("suspect", ["all tests pass"], ts=1.0),
                                     include_thin=True)
    assert rows and all(r.label == 1 for r in rows)


def test_gate_report_counts_suspect_audits_as_misses(tmp_path, capsys):
    gate = tmp_path / "gate.jsonl"
    _write_gate(gate, [_gate("audit", 0.03, claim="audited gamer", ts=200.0)])
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [_entry("suspect", ["audited gamer"], ts=201.0)])
    assert dataset.gate_report(str(gate), str(ledger)) == 0
    out = capsys.readouterr().out
    assert "joined to a verdict     : 1" in out
    assert "turned out FAIL (misses): 1" in out
