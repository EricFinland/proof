import re
from dataclasses import dataclass

@dataclass
class Claim:
    strategy: str
    raw: str
    command: str = ""
    expectation: str = ""

URL_RE = re.compile(r"https?://[^\s)]+")

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
    m = URL_RE.search(text)
    if m or re.search(r"\breturns?\s+200\b|\bendpoint\b", text, re.I):
        url = m.group(0) if m else ""
        exp = "200" if re.search(r"\b200\b", text) else ""
        claims.append(Claim("http", text, command=url, expectation=exp))
    return claims
