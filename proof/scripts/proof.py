# proof/scripts/proof.py
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from proofkit import install

TRIGGER = str(Path(__file__).resolve().parent / "proof_trigger.py")

def _settings(args):
    return Path(args.settings) if args.settings else Path(".claude/settings.json")

def main(argv=None):
    ap = argparse.ArgumentParser(prog="proof")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("arm", "disarm", "status"):
        s = sub.add_parser(name)
        s.add_argument("--settings", default=None)
    v = sub.add_parser("verify")
    v.add_argument("--transcript", required=False, default="")
    v.add_argument("--root", default=".")
    args = ap.parse_args(argv)

    if args.cmd == "arm":
        install.arm(_settings(args), TRIGGER); print("Proof armed."); return 0
    if args.cmd == "disarm":
        install.disarm(_settings(args)); print("Proof disarmed."); return 0
    if args.cmd == "status":
        print("armed" if install.is_armed(_settings(args)) else "disarmed"); return 0
    if args.cmd == "verify":
        from proofkit.verdict import run_verify  # added in M2/M4
        return run_verify(transcript=args.transcript, root=args.root)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
