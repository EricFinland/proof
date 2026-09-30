from proofml.schema import from_ledger_entry


def test_suspect_entry_is_labeled_deceptive():
    rows = from_ledger_entry({"overall": "suspect", "claims": ["tests pass"], "project": "p"})
    assert len(rows) == 1 and rows[0].label == 1


def test_inconclusive_entry_yields_no_rows():
    assert from_ledger_entry({"overall": "inconclusive", "claims": ["x"]}) == []
