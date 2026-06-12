import re
from dataclasses import dataclass

@dataclass
class Claim:
    strategy: str
    raw: str
    command: str = ""
    expectation: str = ""

URL_RE = re.compile(r"https?://[^\s)]+")
_STATUS_RE = re.compile(r'\b(\d{3})\b')


def extract_claims(message: str, root="."):
    text = message or ""
    claims = []
    if re.search(r"\btests?\s+(?:are\s+)?pass", text, re.I) or re.search(r"\ball\s+tests?\s+pass", text, re.I):
        claims.append(Claim("tests", text))
    if re.search(r"\bbuild\s+is\s+(clean|green|passing)\b|\bbuilds?\s+success", text, re.I):
        claims.append(Claim("build", text))
    if re.search(r"\btype-?check", text, re.I):
        claims.append(Claim("typecheck", text))
    if re.search(r"\blint(ing)?\s+(passes|clean)\b", text, re.I):
        claims.append(Claim("lint", text))

    m_url = URL_RE.search(text)
    is_deployed = bool(re.search(r"\bdeployed\b", text, re.I))

    if m_url or re.search(r"\breturns?\s+200\b|\bendpoint\b", text, re.I):
        url = m_url.group(0) if m_url else ""
        m_status = _STATUS_RE.search(text)
        if m_status:
            exp = m_status.group(1)
        elif url or is_deployed:
            # Default to 200 when a URL is present or a deploy claim is made
            exp = "200"
        else:
            exp = ""
        # Only emit an http claim with a URL when the deployed keyword is present
        # without a URL (bare "deployed" without URL stays empty-command, not emitted)
        if url or not is_deployed:
            claims.append(Claim("http", text, command=url, expectation=exp))

    return claims
