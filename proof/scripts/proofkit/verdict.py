import json as _json
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


_CONFIG_STRATEGIES = {"tests", "build", "typecheck", "lint"}
_RUNNER_DETECTORS = {"tests": "detect_test_cmd", "build": "detect_build_cmd"}


def _config_fill(claims, root, cfg):
    """Fill command from .proof.toml for claims with no explicit command.

    Precedence per strategy: claim-explicit > .proof.toml [commands] > auto-detect.
    Config command is checked BEFORE auto-detection so it always wins when set.
    """
    from proofkit.config import cfg_get

    # User-facing config keys are singular ("test", like package.json scripts);
    # the strategy name ("tests") is accepted as an alias.
    key_aliases = {"tests": ("test", "tests")}
    for c in claims:
        if c.command or c.strategy not in _CONFIG_STRATEGIES:
            continue
        for key in key_aliases.get(c.strategy, (c.strategy,)):
            cmd_str = cfg_get(cfg, "commands", key)
            if cmd_str:
                c.command = cmd_str
                break


def _build_json_payload(results, overall, report_path):
    """Build the standard JSON payload dict shared by verify --json and check --json."""
    exit_code = {"pass": 0, "fail": 1, "inconclusive": 2}[overall]
    items = []
    for r in results:
        items.append({
            "claim": r.claim,
            "method": r.method,
            "command": r.command,
            "raw_output": r.raw_output[:2000],
            "verdict": r.verdict,
            "confidence": r.confidence,
        })
    return {
        "overall": overall,
        "exit": exit_code,
        "results": items,
        "report": str(report_path),
    }


def _execute_claims(claims, root, out_dir, project=None, as_json=False):
    """Run all claims through their strategies, write report, append ledger, print verdict.

    Returns an exit code int: 0=pass, 1=fail, 2=inconclusive.
    When as_json=True, prints one JSON object instead of ASCII verdict lines.
    """
    from proofkit import strategies

    if project is None:
        project = Path(root).resolve().name

    results = []
    for c in claims:
        fn = strategies.get(c.strategy)
        if fn:
            results.append(fn(c.raw, root=root,
                              command=c.command or None,
                              expectation=c.expectation or None))
    overall = aggregate(results)
    report_path = write_report(results, overall, out_dir=out_dir)

    # Append ledger entry; never let ledger failures affect the verdict or exit code.
    try:
        from proofkit import ledger as _ledger
        entry = {
            "project": project,
            "overall": overall,
            "n_claims": len(results),
            "fails": [r.method for r in results if r.verdict == "fail"],
            "claims": [r.claim[:120] for r in results],
        }
        _ledger.append_entry(entry)
    except Exception:
        pass

    exit_code = {"pass": 0, "fail": 1, "inconclusive": 2}[overall]

    if as_json:
        payload = _build_json_payload(results, overall, report_path)
        print(_json.dumps(payload))
    else:
        # Print ASCII-safe verdict to stdout (avoids cp1252 encoding errors on Windows).
        print(_ICON[overall])
        for r in results:
            if r.verdict == "fail":
                print(f"  FAIL {r.method}: `{r.command}`")

    return exit_code


def run_verify(transcript="", root=".", out_dir=".", session_id=None, as_json=False):
    from proofkit import strategies
    from proofkit.transcript import last_assistant_text
    from proofkit.extractor import extract_claims
    from proofkit.config import load_config

    strategies.load_all()
    msg = last_assistant_text(transcript) if transcript else ""
    claims = extract_claims(msg, root=root)
    cfg = load_config(root)
    _config_fill(claims, root, cfg)
    exit_code = _execute_claims(claims, root, out_dir,
                                project=Path(root).resolve().name,
                                as_json=as_json)

    # Record outcome into marker when called with a session_id (e.g. from trigger directive).
    if session_id and msg:
        try:
            from proofkit.marker import record_outcome
            verdict_map = {0: "pass", 1: "fail", 2: "inconclusive"}
            verdict = verdict_map.get(exit_code, "inconclusive")
            # Use PROOF_HOME env var for marker root (matches trigger behavior)
            import os
            marker_root = os.environ.get("PROOF_HOME") or None
            record_outcome(session_id, msg, verdict, root=marker_root)
        except Exception:
            pass  # never let marker failures affect the verdict

    return exit_code


def run_check(claim_text, root=".", out_dir=".", as_json=False):
    """Verify any claim text directly, without a transcript.

    Returns an exit code int: 0=pass, 1=fail, 2=inconclusive.
    """
    from proofkit import strategies
    from proofkit.extractor import extract_claims
    from proofkit.config import load_config

    strategies.load_all()
    claims = extract_claims(claim_text, root=root)
    if not claims:
        if as_json:
            payload = {"overall": "inconclusive", "exit": 2, "results": [], "report": ""}
            print(_json.dumps(payload))
        else:
            print("INCONCLUSIVE (no checkable claims found)")
        return 2
    cfg = load_config(root)
    _config_fill(claims, root, cfg)
    return _execute_claims(claims, root, out_dir,
                           project=Path(root).resolve().name,
                           as_json=as_json)
