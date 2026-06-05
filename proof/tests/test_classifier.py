# proof/tests/test_classifier.py
import pytest
from proofkit.classifier import detect_claim

POSITIVE = [
    "All done, tests pass.",
    "Fixed the bug, everything works now.",
    "The endpoint returns 200 — all set.",
    "Build is clean and the feature is complete.",
    "Deployed successfully, it should work now.",
]
NEGATIVE = [
    "I'm working on the failing test now.",
    "What command runs your tests?",
    "This might break if the input is empty.",
    "Let me investigate why the build is red.",
    "",
    # New negatives — must NOT trigger
    "I fixed a typo in the comment.",
    "The done button is broken.",
    "Not done yet.",
    "It is set to debug mode.",
    "Status: complete with errors.",
    "Here is the verified list.",
    "Should work eventually.",
]

@pytest.mark.parametrize("msg", POSITIVE)
def test_detects_completion_claims(msg):
    res = detect_claim(msg)
    assert res.is_claim is True
    assert res.matched  # non-empty list of matched phrases

@pytest.mark.parametrize("msg", NEGATIVE)
def test_ignores_non_claims(msg):
    assert detect_claim(msg).is_claim is False
