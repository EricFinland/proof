# proof/scripts/proof.py
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from proofkit import install
import proofkit

TRIGGER = str(Path(__file__).resolve().parent / "proof_trigger.py")

def _settings(args):
    return Path(args.settings) if args.settings else Path(".claude/settings.json")


def _cmd_stats(args):
    import datetime
    from proofkit import ledger

    root = getattr(args, "root", None)
    days = getattr(args, "days", None)
    as_json = getattr(args, "json", False)

    entries = ledger.read_entries(days=days, root=root)
    stats = ledger.compute_stats(entries)

    if as_json:
        print(json.dumps(stats))
        return 0

    if stats["total"] == 0:
        print("No verifications recorded yet.")
        return 0

    verified = stats["passes"] + stats["fails"]
    rate_pct = round(stats["honesty_rate"] * 100) if stats["honesty_rate"] is not None else 0
    lies = stats["fails"]
    lie_word = "lie" if lies == 1 else "lies"
    print(f"Honesty rate: {rate_pct}% ({verified} verified, {lies} {lie_word} caught)")
    print(f"Clean streak: {stats['clean_streak']}")

    if stats["worst_method"] is not None:
        # Count occurrences for the human label
        from collections import Counter
        mc: Counter = Counter()
        for e in entries:
            if e.get("overall") == "fail":
                for m in e.get("fails", []):
                    mc[m] += 1
        count = mc.get(stats["worst_method"], 0)
        catch_word = "catch" if count == 1 else "catches"
        print(f"Worst offender: {stats['worst_method']} ({count} {catch_word})")

    if stats["last_catch"] is not None:
        ts = stats["last_catch"]["ts"]
        date_str = datetime.date.fromtimestamp(ts).isoformat()
        claim = stats["last_catch"]["claim"]
        print(f'Last catch: "{claim}" ({date_str})')

    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="proof")
    ap.add_argument("--version", action="version",
                    version=f"proof {proofkit.__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("arm", "disarm", "status"):
        s = sub.add_parser(name)
        s.add_argument("--settings", default=None)
    v = sub.add_parser("verify")
    v.add_argument("--transcript", required=False, default="")
    v.add_argument("--root", default=".")
    v.add_argument("--session", default=None, help="Session ID for outcome recording")
    v.add_argument("--out-dir", default=".", dest="out_dir",
                   help="Directory to write proof-report.md (default: current dir)")
    v.add_argument("--json", action="store_true", default=False,
                   help="Emit machine-readable JSON instead of ASCII verdict")
    st = sub.add_parser("stats")
    st.add_argument("--days", type=int, default=None)
    st.add_argument("--json", action="store_true", default=False)
    st.add_argument("--root", default=None)
    ck = sub.add_parser("check")
    ck.add_argument("claim", help="Claim text to verify")
    ck.add_argument("--root", default=".")
    ck.add_argument("--json", action="store_true", default=False,
                    help="Emit machine-readable JSON instead of ASCII verdict")
    args = ap.parse_args(argv)

    if args.cmd == "arm":
        install.arm(_settings(args), TRIGGER); print("Proof armed."); return 0
    if args.cmd == "disarm":
        install.disarm(_settings(args)); print("Proof disarmed."); return 0
    if args.cmd == "status":
        print("armed" if install.is_armed(_settings(args)) else "disarmed"); return 0
    if args.cmd == "verify":
        from proofkit.verdict import run_verify  # added in M2/M4
        return run_verify(transcript=args.transcript, root=args.root,
                          out_dir=getattr(args, "out_dir", "."),
                          session_id=getattr(args, "session", None),
                          as_json=getattr(args, "json", False))
    if args.cmd == "stats":
        return _cmd_stats(args)
    if args.cmd == "check":
        from proofkit.verdict import run_check
        return run_check(claim_text=args.claim, root=args.root,
                         as_json=getattr(args, "json", False))
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
