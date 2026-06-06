from pathlib import Path


def aggregate(results):
    verdicts = [r.verdict for r in results]
    if "fail" in verdicts:
        return "fail"
    if "pass" in verdicts:
        return "pass"
    return "inconclusive"


# Unicode icons for the markdown report only.
_ICON = {"pass": "PASS", "fail": "FAIL", "inconclusive": "INCONCLUSIVE"}
_ICON_MD = {"pass": "PASS", "fail": "FAIL", "inconclusive": "INCONCLUSIVE"}


def write_report(results, overall, out_dir="."):
    out = Path(out_dir) / "proof-report.md"
    lines = [f"# Proof Report -- {_ICON_MD[overall]}", ""]
    for r in results:
        lines += [
            f"## {_ICON_MD[r.verdict]} -- {r.method}",
            f"- **Claim:** {r.claim[:200]}",
            f"- **Command:** `{r.command}`",
            "",
            "```",
            r.raw_output.strip()[:3000],
            "```",
            "",
        ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return str(out)


def run_verify(transcript="", root=".", out_dir="."):
    from proofkit import strategies
    from proofkit.transcript import last_assistant_text
    from proofkit.extractor import extract_claims

    strategies.load_all()
    msg = last_assistant_text(transcript) if transcript else ""
    claims = extract_claims(msg, root=root)
    results = []
    for c in claims:
        fn = strategies.get(c.strategy)
        if fn:
            results.append(fn(c.raw, root=root,
                              command=c.command or None,
                              expectation=c.expectation or None))
    overall = aggregate(results)
    write_report(results, overall, out_dir=out_dir)
    # Print ASCII-safe verdict to stdout (avoids cp1252 encoding errors on Windows).
    print(_ICON[overall])
    for r in results:
        if r.verdict == "fail":
            print(f"  FAIL {r.method}: `{r.command}`")
    return {"pass": 0, "fail": 1, "inconclusive": 2}[overall]
