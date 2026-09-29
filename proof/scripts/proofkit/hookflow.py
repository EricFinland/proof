"""Stop hook decision logic.

decide_stop() is a pure function of the hook payload and working directory. It
returns the JSON object the hook prints, or None to let the turn end. It runs
checks in-process under a time budget and hands only unresolved checks to a
verifier subagent, then refuses to let the turn end until `proof.py verify`
has recorded a verdict for them.
"""
import os
from pathlib import Path

from proofkit.classifier import detect_claim
from proofkit.config import cfg_get, load_config
from proofkit.extractor import extract_claims
from proofkit.transcript import last_assistant_text
from proofkit import marker
from proofkit.strategies.base import Budget

DEFAULT_BUDGET = 90
_OUTPUT_TAIL = 1200

DIRECTIVE = (
    "PROOF: you claimed work is complete. These checks still need an independent "
    "verifier: {pending}. Do NOT stop. Spawn an INDEPENDENT verifier subagent (Task "
    "tool) that follows references/verifier-subagent.md: it must run "
    "`python \"{script}\" verify --transcript \"{tp}\" --root \"{cwd}\" --session "
    "\"{sid}\" --claim-key \"{key}\" --out-dir \"{cwd}\"`, assume your claims may be "
    "false, trust only execution output, and report the PASS/FAIL/SUSPECT/"
    "INCONCLUSIVE verdict with receipts. If FAIL, fix the issues and let Proof "
    "re-verify."
)
NOT_RUN = "PROOF: verification was not run. The claim is still pending. "
FAIL_HEAD = ("PROOF: your completion claim did not survive verification "
             "(attempt {n} of {max}).\n\n")
FAIL_TAIL = ("\n\nFix the failing checks, then claim completion again. Proof will "
             "re-verify automatically.")


def budget_seconds(cfg):
    env = os.environ.get("PROOF_INLINE_BUDGET")
    raw = env if env is not None else cfg_get(cfg, "verify", "inline_budget",
                                              default=DEFAULT_BUDGET)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return float(DEFAULT_BUDGET)


def _script():
    return Path(__file__).resolve().parents[1].joinpath("proof.py").as_posix()


def _directive(pending, tp, cwd, session, key):
    return DIRECTIVE.format(pending=", ".join(pending) or "your claim", script=_script(),
                            tp=Path(tp).as_posix() if tp else "",
                            cwd=Path(cwd).as_posix(), sid=session, key=key)


def _block(reason, system_message=None):
    out = {"decision": "block", "reason": reason}
    if system_message:
        out["systemMessage"] = system_message
    return out


def _fail_receipts(outcome):
    parts = []
    for r in outcome.results:
        if r.verdict in ("fail", "suspect"):
            parts.append(f"{r.verdict.upper()} {r.method}: `{r.command}`\n"
                         f"{r.raw_output.strip()[-_OUTPUT_TAIL:]}")
    return "\n\n".join(parts)


def decide_stop(payload, cwd, marker_root=None):
    session = payload.get("session_id", "unknown")
    tp = payload.get("transcript_path", "")
    active = bool(payload.get("stop_hook_active"))
    cwd = Path(cwd)
    cfg = load_config(str(cwd))
    max_cycles = int(cfg_get(cfg, "verify", "max_fix_cycles", default=3))

    in_fix_chain = False
    if not active:
        marker.chain_reset(session, root=marker_root)
    else:
        state = marker.chain_state(session, root=marker_root)
        if state["count"] >= max_cycles:
            return None
        pend = marker.pending_entry(session, root=marker_root)
        if pend:
            key, entry = pend
            if entry.get("attempts", 0) >= max_cycles:
                return None
            marker.record_attempt(session, entry.get("claim") or "", root=marker_root)
            marker.chain_bump(session, root=marker_root)
            return _block(NOT_RUN + _directive(entry.get("pending", []), tp, cwd,
                                               session, key))
        if state["last"] not in ("fail", "suspect"):
            return None
        in_fix_chain = True

    msg = last_assistant_text(tp)
    if not detect_claim(msg).is_claim:
        return None
    if not marker.should_block(session, msg, max_cycles=max_cycles, root=marker_root):
        return None

    # Only a fresh, first verification may be skipped by the gate. A re-claim inside a
    # fail/suspect chain is always re-verified, even when its wording is new.
    try:
        if not in_fix_chain and marker.last_outcome(session, msg, root=marker_root) is None:
            from proofkit.gate import decide
            g = decide(msg, transcript=tp, root=str(cwd), session=session,
                       marker_root=marker_root)
            if g and g.get("decision") == "skip":
                return None
    except Exception:
        pass

    marker.record_attempt(session, msg, root=marker_root)
    marker.chain_bump(session, root=marker_root)
    return verify_inline(msg, session, tp, cwd, cfg, Budget(budget_seconds(cfg)),
                         marker_root, max_cycles)


def verify_inline(msg, session, tp, cwd, cfg, budget, marker_root, max_cycles):
    from proofkit.verdict import _config_fill, finalize, run_claims

    root = str(cwd)
    key = marker.claim_key(msg)
    claims = extract_claims(msg, root=root)
    _config_fill(claims, root, cfg)
    results = run_claims(claims, root, budget=budget)
    notes = []
    # Tasks 8 and 11 extend `results` and `notes` with analyzer output here.

    if not results:
        marker.set_pending(session, msg, ["unstructured claim"], root=marker_root)
        return _block(_directive(["unstructured claim"], tp, cwd, session, key))

    probe_overall = _peek_overall(results)
    unresolved_only = probe_overall not in ("fail", "suspect") and any(
        r.verdict in ("deferred", "inconclusive") for r in results)
    outcome = finalize(results, root, out_dir=root, transcript=tp,
                       write_ledger=not unresolved_only, notes=notes)
    # The chain's block count (after this attempt's bump) is what caps the fix loop,
    # so it labels the attempt even when the claim was reworded.
    n = marker.chain_state(session, root=marker_root)["count"]

    if outcome.overall == "fail":
        marker.record_outcome(session, msg, "fail", root=marker_root)
        return _block(FAIL_HEAD.format(n=n, max=max_cycles) + _fail_receipts(outcome)
                      + FAIL_TAIL)

    # Task 8 inserts the SUSPECT policy here.

    if outcome.unresolved:
        pending = sorted({r.method for r in outcome.unresolved})
        marker.set_pending(session, msg, pending, root=marker_root)
        return _block(_directive(pending, tp, cwd, session, key))

    marker.record_outcome(session, msg, outcome.overall, root=marker_root)
    methods = ", ".join(sorted({r.method for r in outcome.results}))
    return {"systemMessage": f"Proof: {outcome.overall.upper()} ({methods})"}


def _peek_overall(results):
    from proofkit.verdict import aggregate
    return aggregate(results)
