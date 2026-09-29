"""Findings: evidence that a passing check was gamed, and the SUSPECT result builder."""
import hashlib
from dataclasses import dataclass

from proofkit.strategies.base import Result


@dataclass(frozen=True)
class Finding:
    rule: str
    file: str
    line: int
    snippet: str

    def render(self) -> str:
        loc = self.file
        if loc and self.line:
            loc = f"{loc}:{self.line}"
        head = f"{self.rule}: {loc}" if loc else f"{self.rule}:"
        return f"{head}  {self.snippet.strip()[:160]}"


def findings_hash(findings) -> str:
    """Stable id for a set of findings. Line numbers are excluded on purpose
    because they shift as the code is edited."""
    keys = sorted({(f.rule, f.file, f.snippet.strip()) for f in findings})
    h = hashlib.sha256()
    for k in keys:
        h.update("\x1f".join(k).encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()[:16]


def suspect_result(claim, method, headline, findings, command="") -> Result:
    raw = headline + "\n" + "\n".join(f.render() for f in findings)
    return Result(claim, method, command, raw, "suspect", 0.9, list(findings))


def is_comment_line(text: str) -> bool:
    s = text.strip()
    if not s:
        return True
    if s.startswith(("//", "/*", "*", "<!--")):
        return True
    return s.startswith("#") and not s.startswith("#[")
