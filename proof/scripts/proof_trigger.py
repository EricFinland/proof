# proof/scripts/proof_trigger.py
import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proofkit.classifier import detect_claim
from proofkit.transcript import last_assistant_text
from proofkit.marker import already_verified, mark_verified

DIRECTIVE = (
    "PROOF: you just claimed work is complete. Do NOT stop. Spawn an INDEPENDENT "
    "verifier subagent (Task tool) that follows references/verifier-subagent.md: it "
    "must run `python {script} verify --transcript \"{tp}\"`, assume your claims may "
    "be false, trust only execution output, and report the PASS/FAIL/INCONCLUSIVE "
    "verdict with receipts. If FAIL, fix the issues and let Proof re-verify."
)

def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return  # never break a turn on hook error
    if payload.get("stop_hook_active"):
        return
    tp = payload.get("transcript_path", "")
    session = payload.get("session_id", "unknown")
    root = os.environ.get("PROOF_HOME")  # tests inject; prod uses default (~/.proof)
    msg = last_assistant_text(tp)
    if not detect_claim(msg).is_claim:
        return
    if already_verified(session, msg, root=root):
        return
    mark_verified(session, msg, root=root)
    script = str(Path(__file__).resolve().parent / "proof.py")
    print(json.dumps({
        "decision": "block",
        "reason": DIRECTIVE.format(script=script, tp=tp),
    }))

if __name__ == "__main__":
    main()
