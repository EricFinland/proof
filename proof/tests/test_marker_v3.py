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


def test_set_pending_demotes_other_pending_in_session(tmp_path):
    other = "Build is green now."
    m.set_pending("s", other, ["build"], root=tmp_path)
    m.set_pending("s2", other, ["build"], root=tmp_path)
    m.set_pending("s", MSG, ["tests"], root=tmp_path)
    key, entry = m.pending_entry("s", root=tmp_path)
    assert key == m.claim_key(MSG) and entry["pending"] == ["tests"]
    data = m._load(tmp_path)
    demoted = data["s"][m.claim_key(other)]
    assert demoted["last"] is None and demoted["pending"] == []
    # other sessions are untouched
    assert m.pending_entry("s2", root=tmp_path)[0] == m.claim_key(other)


LONG = ("Here is a long summary of the work. " * 170) + "All 250 tests pass."


def test_long_claim_is_stored_whole_and_still_extracts_tests(tmp_path):
    from proofkit.extractor import extract_claims
    assert len(LONG) > 6000
    m.record_attempt("s", LONG, root=tmp_path)
    stored = m.get_claim("s", m.claim_key(LONG), root=tmp_path)
    assert stored == LONG.strip()
    assert "tests" in {c.strategy for c in extract_claims(stored, root=str(tmp_path))}
    m.set_pending("s", LONG, ["tests"], root=tmp_path)
    assert m.get_claim("s", m.claim_key(LONG), root=tmp_path) == LONG.strip()


def test_claim_text_is_capped(tmp_path):
    huge = "x" * 60000 + " All tests pass."
    m.record_attempt("s", huge, root=tmp_path)
    assert len(m.get_claim("s", m.claim_key(huge), root=tmp_path)) == 50000


def test_record_attempt_by_key_bumps_that_key(tmp_path):
    m.record_attempt("s", LONG, root=tmp_path)
    m.record_attempt_by_key("s", m.claim_key(LONG), root=tmp_path)
    assert m.attempts("s", LONG, root=tmp_path) == 2
    assert m.get_claim("s", m.claim_key(LONG), root=tmp_path) == LONG.strip()


def test_save_uses_pid_unique_tmp_and_retries_replace(tmp_path, monkeypatch):
    import os
    real = os.replace
    calls = []

    def flaky(src, dst):
        calls.append(str(src))
        if len(calls) < 3:
            raise PermissionError("file in use")
        return real(src, dst)

    monkeypatch.setattr(m.os, "replace", flaky)
    m.record_attempt("s", MSG, root=tmp_path)
    assert len(calls) == 3 and all(f"verified.{os.getpid()}.tmp" in c for c in calls)
    assert m.attempts("s", MSG, root=tmp_path) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_save_failure_keeps_old_file(tmp_path, monkeypatch):
    import os
    import pytest
    m.record_attempt("s", MSG, root=tmp_path)
    before = (tmp_path / "verified.json").read_text(encoding="utf-8")

    def locked(src, dst):
        raise PermissionError("file in use")

    monkeypatch.setattr(m.os, "replace", locked)
    with pytest.raises(PermissionError):
        m.record_attempt("s", MSG, root=tmp_path)
    assert (tmp_path / "verified.json").read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob("*.tmp"))
