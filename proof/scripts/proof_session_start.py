# proof/scripts/proof_session_start.py
"""SessionStart hook: capture a repository baseline for this session."""
import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    try:
        payload = json.load(sys.stdin)
        from proofkit.config import cfg_get, load_config
        cwd = Path(payload.get("cwd") or os.getcwd())
        if cfg_get(load_config(str(cwd)), "baseline", "enabled", default=True) is False:
            return
        from proofkit.baseline import capture
        capture(cwd, payload.get("session_id", "unknown"),
                marker_root=os.environ.get("PROOF_HOME") or None)
    except Exception:
        return


if __name__ == "__main__":
    main()
