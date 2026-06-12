# proof/scripts/proof_trigger.py
import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proofkit.classifier import detect_claim
from proofkit.transcript import last_assistant_text
from proofkit.marker import should_block, record_attempt, attempts, last_outcome
from proofkit.config import load_config, cfg_get

DIRECTIVE = (
    "PROOF: you just claimed work is complete. Do NOT stop. Spawn an INDEPENDENT "
    "verifier subagent (Task tool) that follows references/verifier-subagent.md: it "
    "must run `python {script} verify --transcript \"{tp}\" --root \"{cwd}\""
    " --session \"{sid}\"`, assume your claims may "
    "be false, trust only execution output, and report the PASS/FAIL/INCONCLUSIVE "
    "verdict with receipts. If FAIL, fix the issues and let Proof re-verify."
)

_RECEIPT_LIMIT = 1500


def main():
    try:
        payload = json.load(sys.stdin)
        if payload.get("stop_hook_active"):
            return
        tp = payload.get("transcript_path", "")
        session = payload.get("session_id", "unknown")

        # marker root: PROOF_HOME env var (tests inject; prod uses default ~/.proof)
        marker_root = os.environ.get("PROOF_HOME") or None

        msg = last_assistant_text(tp)
        if not detect_claim(msg).is_claim:
            return

        # Read max_fix_cycles from .proof.toml in CWD
        cwd_path = Path.cwd()
        cfg = load_config(str(cwd_path))
        max_cycles = cfg_get(cfg, "verify", "max_fix_cycles", default=3)

        if not should_block(session, msg, max_cycles=max_cycles, root=marker_root):
            return

        # Record that we are making an attempt now
        record_attempt(session, msg, root=marker_root)
        current_attempts = attempts(session, msg, root=marker_root)

        script = Path(__file__).resolve().parent.joinpath("proof.py").as_posix()
        tp_posix = Path(tp).as_posix() if tp else ""
        cwd_posix = cwd_path.as_posix()

        reason = DIRECTIVE.format(
            script=script, tp=tp_posix, cwd=cwd_posix, sid=session
        )

        # If this is a re-block after a prior fail AND a proof-report.md exists in CWD,
        # prepend the receipt context.
        prior_outcome = last_outcome(session, msg, root=marker_root)
        if current_attempts >= 2 and prior_outcome == "fail":
            report_path = cwd_path / "proof-report.md"
            if report_path.exists():
                try:
                    receipt_text = report_path.read_text(encoding="utf-8", errors="replace")
                    receipt_snippet = receipt_text[:_RECEIPT_LIMIT]
                    attempt_note = (
                        f"This is attempt {current_attempts} of {max_cycles}. "
                        "Fix the failing checks before claiming done."
                    )
                    reason = (
                        "PREVIOUS RECEIPTS:\n"
                        + receipt_snippet
                        + "\n"
                        + attempt_note
                        + "\n\n"
                        + reason
                    )
                except Exception:
                    pass

        print(json.dumps({
            "decision": "block",
            "reason": reason,
        }))
    except Exception:
        return  # never break a turn on hook error


if __name__ == "__main__":
    main()
