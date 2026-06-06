# proof/tests/test_classifier.py
import pytest
from proofkit.classifier import detect_claim

POSITIVE = [
    "All done, tests pass.",
    "Fixed the bug, everything works now.",
    "The endpoint returns 200 — all set.",
    "Build is clean and the feature is complete.",
    "Deployed successfully, it should work now.",
    # FIX 2: successfully + completion-scope verb still triggers
    "Successfully deployed to production.",
    # FIX 3: "deployed to production" still triggers
    "Deployed to production.",
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
    # FIX 2: successfully + routine verb must NOT trigger
    "Successfully renamed the variable.",
    "Successfully copied the file.",
    "Successfully updated the config.",
    # FIX 3: future/passive forms must NOT trigger
    "This will be deployed to production later.",
    "The app is being deployed.",
    "To be deployed next sprint.",
]

@pytest.mark.parametrize("msg", POSITIVE)
def test_detects_completion_claims(msg):
    res = detect_claim(msg)
    assert res.is_claim is True
    assert res.matched  # non-empty list of matched phrases

@pytest.mark.parametrize("msg", NEGATIVE)
def test_ignores_non_claims(msg):
    assert detect_claim(msg).is_claim is False
