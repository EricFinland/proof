from pathlib import Path
from proofkit.strategies import register
from proofkit.strategies.base import Result


@register("filecheck")
def verify_filecheck(claim, root, command=None, expectation=None):
    symbol = command or ""
    target = expectation or ""
    p = Path(root) / target if target else None
    if not p or not p.exists():
        return Result(
            claim, "filecheck", target, f"file not found: {target}", "inconclusive", 0.3
        )
    text = p.read_text(encoding="utf-8", errors="ignore")
    found = symbol in text
    return Result(
        claim,
        "filecheck",
        f"grep {symbol} {target}",
        f"{'found' if found else 'absent'}: {symbol}",
        "pass" if found else "fail",
    )
