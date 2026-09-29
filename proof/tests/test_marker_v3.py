import json
from proofkit import marker as m

MSG = "All done, tests pass."


def test_attempt_stores_claim(tmp_path):
    m.record_attempt("s", MSG, root=tmp_path)
    assert m.get_claim("s", m.claim_key(MSG), root=tmp_path) == MSG


def test_pending_roundtrip(tmp_path):
    m.set_pending("s", MSG, ["tests"], root=tmp_path)
    key, entry = m.pending_entry("s", root=tmp_path)
    assert key == m.claim_key(MSG) and entry["pending"] == ["tests"]
    m.record_outcome_by_key("s", key, "pass", root=tmp_path)
    assert m.pending_entry("s", root=tmp_path) is None
    assert m.chain_state("s", root=tmp_path)["last"] == "pass"


def test_chain_bump_reset(tmp_path):
    assert m.chain_bump("s", root=tmp_path) == 1
    assert m.chain_bump("s", root=tmp_path) == 2
    m.chain_reset("s", root=tmp_path)
    assert m.chain_state("s", root=tmp_path) == {"count": 0, "last": None}


def test_suspect_seen(tmp_path):
    assert not m.suspect_seen("s", "abc", root=tmp_path)
    m.mark_suspect_seen("s", "abc", root=tmp_path)
    assert m.suspect_seen("s", "abc", root=tmp_path)


def test_meta_keys_do_not_break_attempts(tmp_path):
    m.chain_bump("s", root=tmp_path)
    m.mark_suspect_seen("s", "h", root=tmp_path)
    assert m.attempts("s", MSG, root=tmp_path) == 0
    assert m.pending_entry("s", root=tmp_path) is None


def test_should_block_v3(tmp_path):
    m.record_attempt("s", MSG, root=tmp_path)
    m.record_outcome("s", MSG, "suspect", root=tmp_path)
    assert m.should_block("s", MSG, max_cycles=3, root=tmp_path)
    m.set_pending("s", MSG, ["tests"], root=tmp_path)
    assert m.should_block("s", MSG, max_cycles=3, root=tmp_path)
    m.record_outcome("s", MSG, "inconclusive", root=tmp_path)
    assert not m.should_block("s", MSG, max_cycles=3, root=tmp_path)


def test_v2_file_migrates(tmp_path):
    (tmp_path / "verified.json").write_text(json.dumps(
        {"s": {m.claim_key(MSG): {"attempts": 1, "last": "fail"}}}), encoding="utf-8")
    assert m.attempts("s", MSG, root=tmp_path) == 1
    assert m.get_claim("s", m.claim_key(MSG), root=tmp_path) is None
