import json as _json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from proofkit.strategies.base import Budget, DEFAULT_COMMAND_TIMEOUT, Result

EXIT = {"pass": 0, "fail": 1, "inconclusive": 2, "suspect": 3}
_ICON = {"pass": "PASS", "fail": "FAIL", "inconclusive": "INCONCLUSIVE",
         "suspect": "SUSPECT", "deferred": "DEFERRED"}
_ICON_MD = dict(_ICON)


def aggregate(results):
    seen = {"inconclusive" if r.verdict == "deferred" else r.verdict for r in results}
    for level in ("fail", "suspect", "pass"):
        if level in seen:
            return level
    return "inconclusive"


@dataclass
class Outcome:
    overall: str
    results: list
    report_path: str
    notes: list = field(default_factory=list)

    @property
    def exit_code(self):
        return EXIT[self.overall]

    @property
    def deferred(self):
        return [r for r in self.results if r.verdict == "deferred"]

    @property
    def unresolved(self):
        return [r for r in self.results if r.verdict in ("deferred", "inconclusive")]


def write_report(results, overall, out_dir=".", notes=()):
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
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
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
    exit_code = EXIT[overall]
    items = []
    for r in results:
        items.append({
            "claim": r.claim,
            "method": r.method,
            "command": r.command,
            "raw_output": r.raw_output[:2000],
            "verdict": r.verdict,
            "confidence": r.confidence,
            "findings": [asdict(f) for f in r.findings],
        })
    return {
        "overall": overall,
        "exit": exit_code,
        "results": items,
        "report": str(report_path),
    }


def run_claims(claims, root, budget=None, command_timeout=DEFAULT_COMMAND_TIMEOUT):
    """Run each claim through its strategy under an optional shared budget."""
    from proofkit import strategies

    strategies.load_all()
    budget = budget or Budget(None)
    results = []
    for c in claims:
        fn = strategies.get(c.strategy)
        if not fn:
            continue
        if budget.exhausted():
            results.append(Result(c.raw, c.strategy, c.command,
                                  "not started: inline budget exhausted", "deferred", 0.0))
            continue
        results.append(fn(c.raw, root=root, command=c.command or None,
                          expectation=c.expectation or None,
                          timeout=budget.timeout(command_timeout)))
    return results


def finalize(results, root, out_dir, project=None, transcript="", write_ledger=True,
             notes=None):
    """Aggregate results, write the report, append the ledger entry. Never prints."""
    if project is None:
        project = Path(root).resolve().name
    notes = notes or []
    overall = aggregate(results)
    report_path = write_report(results, overall, out_dir=out_dir, notes=notes)

    if write_ledger:
        # Never let ledger failures affect the verdict or exit code.
        try:
            from proofkit import ledger as _ledger
            entry = {
                "project": project,
                "overall": overall,
                "n_claims": len(results),
                "fails": [r.method for r in results if r.verdict == "fail"],
                "suspects": [r.method for r in results if r.verdict == "suspect"],
                "claims": [r.claim[:120] for r in results],
            }
            # Shadow mode (opt-in, additive): when enabled, enrich the ledger entry
            # with a deception prediction. Guarded so it can never affect the
            # verdict, exit code, or printed output. When OFF, maybe_predict returns
            # None and the entry is byte-for-byte what it was before.
            try:
                from proofkit.shadow import maybe_predict
                primary_claim = results[0].claim if results else ""
                sh = maybe_predict(primary_claim, transcript=transcript, root=root)
                if sh:
                    entry["shadow_proba"] = sh["proba"]
                    entry["shadow_model"] = sh["model"]
                    entry["shadow_source"] = sh["source"]
                    entry["behavior"] = sh["behavior"]
            except Exception:
                pass
            _ledger.append_entry(entry)
        except Exception:
            pass

    return Outcome(overall, results, report_path, notes)


def print_outcome(outcome, as_json=False):
    """Print the verdict to stdout: one JSON object, or ASCII lines."""
    if as_json:
        print(_json.dumps(_build_json_payload(outcome.results, outcome.overall,
                                              outcome.report_path)))
        return
    # ASCII-safe verdict (avoids cp1252 encoding errors on Windows).
    print(_ICON[outcome.overall])
    for r in outcome.results:
        if r.verdict == "fail":
            print(f"  FAIL {r.method}: `{r.command}`")
        elif r.verdict == "suspect":
            for line in r.raw_output.splitlines()[1:]:
                print(f"  SUSPECT {r.method}: {line}")


def _command_timeout(cfg):
    from proofkit.config import cfg_get
    try:
        return int(cfg_get(cfg, "verify", "command_timeout", default=DEFAULT_COMMAND_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_COMMAND_TIMEOUT


def _execute_claims(claims, root, out_dir, project=None, as_json=False, transcript="",
                    extra=None, notes=None, command_timeout=DEFAULT_COMMAND_TIMEOUT):
    """Run all claims, write report, append ledger, print verdict.

    Returns an exit code int: 0=pass, 1=fail, 2=inconclusive, 3=suspect.
    When as_json=True, prints one JSON object instead of ASCII verdict lines.
    """
    results = run_claims(claims, root, command_timeout=command_timeout)
    outcome = finalize(results + list(extra or []), root, out_dir,
                       project, transcript, notes=notes)
    print_outcome(outcome, as_json)
    return outcome.exit_code


def run_verify(transcript="", root=".", out_dir=".", session_id=None, as_json=False,
               claim_key=None, since=None):
    import os
    from proofkit import strategies
    from proofkit.transcript import last_assistant_text
    from proofkit.extractor import extract_claims
    from proofkit.config import load_config

    strategies.load_all()
    marker_root = os.environ.get("PROOF_HOME") or None
    msg = ""
    if claim_key and session_id:
        try:
            from proofkit.marker import get_claim
            msg = get_claim(session_id, claim_key, root=marker_root) or ""
        except Exception:
            msg = ""
    if not msg and transcript:
        msg = last_assistant_text(transcript)
    claims = extract_claims(msg, root=root)
    cfg = load_config(root)
    _config_fill(claims, root, cfg)
    extra, notes = _analyze(msg, claims, root, cfg, session_id, since,
                            marker_root=marker_root)
    exit_code = _execute_claims(claims, root, out_dir,
                                project=Path(root).resolve().name,
                                as_json=as_json,
                                transcript=transcript, extra=extra, notes=notes,
                                command_timeout=_command_timeout(cfg))

    # Record outcome into marker when called with a session_id (e.g. from trigger directive).
    if session_id and (msg or claim_key):
        try:
            from proofkit.marker import record_outcome, record_outcome_by_key
            verdict_map = {v: k for k, v in EXIT.items()}
            verdict = verdict_map.get(exit_code, "inconclusive")
            tree = None
            if verdict in ("pass", "inconclusive"):
                from proofkit.gitutil import fingerprint
                tree = fingerprint(root)
            if claim_key:
                record_outcome_by_key(session_id, claim_key, verdict, root=marker_root,
                                      tree=tree)
            else:
                record_outcome(session_id, msg, verdict, root=marker_root, tree=tree)
        except Exception:
            pass  # never let marker failures affect the verdict

    return exit_code


def _analyze(msg, claims, root, cfg, session_id, since, marker_root=None):
    """Run the diff-based analyzers. Never raises."""
    try:
        from proofkit.analyze import run_analyzers
        from proofkit.changeset import for_claim
        from proofkit.strategies.base import Budget
        changes = for_claim(root, session=session_id, since=since, marker_root=marker_root)
        return run_analyzers(msg, claims, root, cfg, changes, Budget(None))
    except Exception as e:
        return [], [f"analysis skipped: {e}"]


def run_check(claim_text, root=".", out_dir=".", as_json=False, since=None):
    """Verify any claim text directly, without a transcript.

    Returns an exit code int: 0=pass, 1=fail, 2=inconclusive, 3=suspect.
    """
    from proofkit import strategies
    from proofkit.extractor import extract_claims
    from proofkit.config import load_config

    strategies.load_all()
    claims = extract_claims(claim_text, root=root)
    cfg = load_config(root)
    _config_fill(claims, root, cfg)
    extra, notes = _analyze(claim_text, claims, root, cfg, None, since)
    if not claims and not extra:
        if as_json:
            payload = {"overall": "inconclusive", "exit": 2, "results": [], "report": ""}
            print(_json.dumps(payload))
        else:
            print("INCONCLUSIVE (no checkable claims found)")
        return 2
    return _execute_claims(claims, root, out_dir,
                           project=Path(root).resolve().name,
                           as_json=as_json, extra=extra, notes=notes,
                           command_timeout=_command_timeout(cfg))
