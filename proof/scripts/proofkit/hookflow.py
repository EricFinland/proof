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
from proofkit import gitutil, marker
from proofkit.strategies.base import Budget

DEFAULT_BUDGET = 90
_OUTPUT_TAIL = 1200

DIRECTIVE = (
    "PROOF: you claimed work is complete. These checks still need an independent "
    "verifier: {pending}. Do NOT stop. Spawn an INDEPENDENT verifier subagent (Task "
    "tool) that follows references/verifier-subagent.md: it must run "
    "`python \"{script}\" verify --transcript \"{tp}\" --root \"{cwd}\" --session "
    "\"{sid}\" --claim-key \"{key}\" --out-dir \"{cwd}\"` with the Bash tool's maximum "
    "timeout (600000 ms), assume your claims may be "
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


def _with_hint(reason, notes):
    from proofkit.analyze import REPRO_HINT
    if REPRO_HINT in (notes or []):
        return reason + "\n\n" + REPRO_HINT
    return reason


def _fail_receipts(outcome):
    parts = []
    for r in outcome.results:
        if r.verdict in ("fail", "suspect"):
            parts.append(f"{r.verdict.upper()} {r.method}: `{r.command}`\n"
                         f"{r.raw_output.strip()[-_OUTPUT_TAIL:]}")
    return "\n\n".join(parts)


_SUMMARY_LINES = 20


def _summary(outcome):
    """Up to 20 rendered finding or failure lines for the chain record."""
    lines = []
    for r in outcome.results:
        if r.verdict not in ("fail", "suspect"):
            continue
        if r.findings:
            lines += [f"{r.verdict.upper()} {r.method}: {f.render()}" for f in r.findings]
            continue
        lines.append(f"{r.verdict.upper()} {r.method}: `{r.command}`")
        tail = [ln.rstrip() for ln in r.raw_output.strip().splitlines() if ln.strip()]
        lines += ["  " + ln[:200] for ln in tail[-5:]]
    return "\n".join(lines[:_SUMMARY_LINES]) or None


def _final_message(session, marker_root, pend=None):
    """What the user is told when the chain ends without a passing re-verification."""
    last = marker.chain_state(session, root=marker_root)["last"]
    if last in ("fail", "suspect"):
        summary = marker.chain_summary(session, root=marker_root) or "see proof-report.md"
        return {"systemMessage": f"Proof: {last.upper()}. The last verification of the "
                                 "completion claim did not pass, and it was not re-verified "
                                 "before the turn ended:\n" + summary}
    if pend:
        checks = ", ".join(pend[1].get("pending") or []) or "the claim"
        return {"systemMessage": "Proof: INCONCLUSIVE. The completion claim was never "
                                 f"verified: the independent verifier did not run ({checks})."}
    return None


def _forget_if_tree_changed(session, msg, cwd, marker_root):
    """A pass or inconclusive only covers the tree it was measured on. If the same
    claim comes back after the tree changed, it is verified again as a fresh claim.
    Outside git there is no fingerprint and the earlier outcome stands."""
    try:
        if marker.last_outcome(session, msg, root=marker_root) not in ("pass", "inconclusive"):
            return
        before = marker.claim_tree(session, msg, root=marker_root)
        if not before:
            return
        now = gitutil.fingerprint(cwd)
        if now and now != before:
            marker.reset_claim(session, msg, root=marker_root)
    except Exception:
        pass


def decide_stop(payload, cwd, marker_root=None):
    session = payload.get("session_id", "unknown")
    tp = payload.get("transcript_path", "")
    active = bool(payload.get("stop_hook_active"))
    cwd = Path(cwd)
    cfg = load_config(str(cwd))
    max_cycles = int(cfg_get(cfg, "verify", "max_fix_cycles", default=3))

    in_fix_chain = False
    if not active:
        # A new turn: nothing from an earlier turn is still owed a verifier.
        marker.chain_reset(session, root=marker_root)
        marker.clear_pending(session, root=marker_root)
    else:
        state = marker.chain_state(session, root=marker_root)
        pend = marker.pending_entry(session, root=marker_root)
        if state["count"] >= max_cycles:
            return _final_message(session, marker_root, pend)
        exhausted = None
        if pend:
            key, entry = pend
            if entry.get("attempts", 0) < max_cycles:
                marker.record_attempt_by_key(session, key, root=marker_root)
                marker.chain_bump(session, root=marker_root)
                return _block(NOT_RUN + _directive(entry.get("pending", []), tp, cwd,
                                                   session, key))
            # Exhausted: stop asking for it, and let the normal chain logic decide.
            marker.clear_pending(session, root=marker_root, key=key)
            exhausted = pend
        if state["last"] not in ("fail", "suspect"):
            return _final_message(session, marker_root, exhausted)
        in_fix_chain = True

    msg = last_assistant_text(tp)
    if not detect_claim(msg).is_claim:
        return _final_message(session, marker_root) if in_fix_chain else None
    _forget_if_tree_changed(session, msg, cwd, marker_root)
    if not marker.should_block(session, msg, max_cycles=max_cycles, root=marker_root):
        return _final_message(session, marker_root) if in_fix_chain else None

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
    from proofkit.verdict import _command_timeout, _config_fill, finalize, run_claims

    root = str(cwd)
    key = marker.claim_key(msg)
    timeout = _command_timeout(cfg)
    claims = extract_claims(msg, root=root)
    _config_fill(claims, root, cfg)
    from proofkit.analyze import run_analyzers
    from proofkit.changeset import for_claim
    # The change set is taken before any check runs, so files the checks create
    # (test artifacts, caches) are never counted as the agent's changes.
    changes = for_claim(root, session=session, marker_root=marker_root)
    results = run_claims(claims, root, budget=budget, command_timeout=timeout)
    try:
        extra, notes = run_analyzers(msg, claims, root, cfg, changes, budget,
                                     marker_root=marker_root, command_timeout=timeout)
    except Exception as e:  # analysis must never stop verification
        extra, notes = [], [f"analysis skipped: {e}"]
    results += extra

    if not results:
        marker.set_pending(session, msg, ["unstructured claim"], root=marker_root)
        return _block(_with_hint(_directive(["unstructured claim"], tp, cwd, session, key),
                                 notes))

    probe_overall = _peek_overall(results)
    unresolved_only = probe_overall not in ("fail", "suspect") and any(
        r.verdict in ("deferred", "inconclusive") for r in results)
    outcome = finalize(results, root, out_dir=root, transcript=tp,
                       write_ledger=not unresolved_only, notes=notes)
    # The chain's block count (after this attempt's bump) is what caps the fix loop,
    # so it labels the attempt even when the claim was reworded.
    n = marker.chain_state(session, root=marker_root)["count"]

    if outcome.overall == "fail":
        marker.record_outcome(session, msg, "fail", root=marker_root,
                              summary=_summary(outcome))
        return _block(_with_hint(FAIL_HEAD.format(n=n, max=max_cycles)
                                 + _fail_receipts(outcome) + FAIL_TAIL, notes))

    system_message = None
    if outcome.overall == "suspect":
        from proofkit.findings import findings_hash
        found = [f for r in outcome.results if r.verdict == "suspect" for f in r.findings]
        text = "\n".join(f.render() for f in found)
        h = findings_hash(found)
        marker.record_outcome(session, msg, "suspect", root=marker_root,
                              summary=_summary(outcome))
        if not marker.suspect_seen(session, h, root=marker_root):
            marker.mark_suspect_seen(session, h, root=marker_root)
            # On the last chain slot no later stop can show the user these findings,
            # so they go out as a message instead of a block.
            if n < max_cycles:
                return _block(
                    "PROOF: the checks pass, but the change looks like it games them:\n\n"
                    + text + "\n\nRevert these changes, or explain why each one is "
                    "intentional. If they are intentional, Proof will show them to the "
                    "user instead of blocking again.")
        system_message = ("Proof: SUSPECT. The agent was asked about these once and they "
                          "remain. Please review:\n" + text)

    if outcome.unresolved:
        pending = sorted({r.method for r in outcome.unresolved})
        marker.set_pending(session, msg, pending, root=marker_root)
        return _block(_with_hint(_directive(pending, tp, cwd, session, key), notes),
                      system_message)

    if outcome.overall != "suspect":
        tree = (gitutil.fingerprint(root) if outcome.overall in ("pass", "inconclusive")
                else None)
        marker.record_outcome(session, msg, outcome.overall, root=marker_root, tree=tree)
    if system_message:
        return {"systemMessage": system_message}
    methods = ", ".join(sorted({r.method for r in outcome.results}))
    return {"systemMessage": f"Proof: {outcome.overall.upper()} ({methods})"}


def _peek_overall(results):
    from proofkit.verdict import aggregate
    return aggregate(results)
