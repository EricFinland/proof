# Hook Setup & Recursion Guard

Proof installs a `Stop` hook running `python proof_trigger.py`.

- The hook reads `{session_id, transcript_path, stop_hook_active}` from stdin.
- It no-ops when `stop_hook_active` is true (prevents infinite verify loops).
- It no-ops when the last assistant message contains no completion claim.
- It records each verified claim per session (`~/.proof/verified.json`) so the
  same claim is never verified twice.
- On a fresh claim it prints `{"decision":"block","reason": <verifier directive>}`.

Arm with `python proof.py arm`, remove with `python proof.py disarm`.
