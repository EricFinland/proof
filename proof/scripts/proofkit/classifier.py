# proof/scripts/proofkit/classifier.py
import re
from dataclasses import dataclass, field

# Assertive completion signals. Word-boundary, case-insensitive.
# These are phrase-anchored to avoid false positives on incidental words.
CLAIM_PATTERNS = [
    # Test/build signals
    r"\btests?\s+(?:are\s+)?pass(?:ing|ed|es)?\b",
    r"\ball\s+tests?\s+pass\b",
    r"\bbuild\s+is\s+(?:clean|green|passing)\b",
    # "works now" - requires "now" to anchor completion
    r"\b(?:it|everything|this)\s+works?\s+now\b",
    r"\bworks?\s+now\b",
    # "all set" as a phrase (not bare "set")
    r"\ball\s+set\b",
    # "done" only as standalone completion: "all done", "we're done", sentence-final "done."
    # NOT "done button", "not done", "done yet"
    r"\ball\s+done\b",
    r"\b(?:we'?re|i'?m)\s+done\b",
    # Phrase-anchored "fixed"
    r"\b(?:bug|issue|it|that|the\s+\w+)\s+is\s+(?:now\s+)?fixed\b",
    r"\bnow\s+fixed\b",
    r"\bi'?ve\s+fixed\b",
    r"\bi\s+fixed\s+the\b",
    # "complete" only in assertive contexts
    r"\bfeature\s+is\s+complete\b",
    # "successfully" only with a meaningful completion-scope verb
    r"\bsuccessfully\s+(?:deployed|installed|migrated|completed|finished|built|published|released)\b",
    # Deployment
    r"\bdeployed\s+successfully\b",
    r"\bdeployed\b",   # "deployed to production", "deployed successfully", etc. (future/passive blocked by NEGATORS)
    # HTTP success signal
    r"\breturns?\s+200\b",
]

# Patterns that, when matched, cancel a CLAIM_PATTERNS hit.
# Applied BEFORE pattern matching.
NEGATORS = [
    r"\?\s*$",           # ends with a question
    r"\blet me\b",
    r"\bi'?m\s+working\b",
    r"\bmight\b",
    r"\binvestigate\b",
    r"\bnot\s+done\b",   # "not done yet"
    r"\bnot\s+deployed\b",
    r"\bbeing\s+deployed\b",
    r"\bwill\s+be\s+deployed\b",   # future: "will be deployed to X"
    r"\bto\s+be\s+deployed\b",     # passive future: "to be deployed"
]

@dataclass
class ClaimResult:
    is_claim: bool
    matched: list = field(default_factory=list)

def detect_claim(message: str) -> ClaimResult:
    if not message or not message.strip():
        return ClaimResult(False)
    text = message.strip()
    if any(re.search(n, text, re.IGNORECASE) for n in NEGATORS):
        # A negator anywhere suppresses weak claims; keep it simple for v1.
        if not re.search(r"\btests?\s+pass", text, re.IGNORECASE):
            return ClaimResult(False)
    matched = [p for p in CLAIM_PATTERNS if re.search(p, text, re.IGNORECASE)]
    return ClaimResult(bool(matched), matched)
