# proof/scripts/proof_trigger.py
import contextlib, io, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proofkit.hookflow import DIRECTIVE, decide_stop  # noqa: F401  (DIRECTIVE re-exported)


def main():
    try:
        payload = json.load(sys.stdin)
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            out = decide_stop(payload, Path.cwd(),
                              marker_root=os.environ.get("PROOF_HOME") or None)
        if out:
            print(json.dumps(out))
    except Exception:
        return  # never break a turn on hook error


if __name__ == "__main__":
    main()
