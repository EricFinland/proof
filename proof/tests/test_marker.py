# proof/tests/test_marker.py
from proofkit.marker import already_verified, mark_verified, claim_key

def test_claim_key_is_stable():
    assert claim_key("All done, tests pass.") == claim_key("All done, tests pass.")

def test_marks_and_detects(tmp_path):
    sess = "sess-123"
    msg = "All done, tests pass."
    assert already_verified(sess, msg, root=tmp_path) is False
    mark_verified(sess, msg, root=tmp_path)
    assert already_verified(sess, msg, root=tmp_path) is True

def test_different_claim_not_marked(tmp_path):
    sess = "sess-123"
    mark_verified(sess, "tests pass", root=tmp_path)
    assert already_verified(sess, "build is clean", root=tmp_path) is False
