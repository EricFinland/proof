# proof/scripts/proofkit/classifier.py
import re
from dataclasses import dataclass, field

# Assertive completion signals. Word-boundary, case-insensitive.
CLAIM_PATTERNS = [
    r"\btests?\s+(?:are\s+)?pass(?:ing|ed|es)?\b",
    r"\ball\s+tests?\s+pass\b",
    r"\bbuild\s+is\s+(?:clean|green|passing)\b",
    r"\b(?:it|everything|this)\s+works?\s+now\b",
    r"\bworks?\s+now\b",
    r"\b(?:all\s+)?(?:set|done)\b",
    r"\bfixed\b",
    r"\bcomplete(?:d|ly)?\b",
    r"\bdeployed\b",
    r"\bverified\b",
    r"\bshould\s+work\b",
    r"\breturns?\s+200\b",
]
# Phrases that negate a nearby claim (questions, future intent).
NEGATORS = [r"\?\s*$", r"\blet me\b", r"\bi'?m\s+working\b", r"\bmight\b", r"\binvestigate\b"]

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
