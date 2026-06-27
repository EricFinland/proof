"""Bootstrap balanced honest/deceptive Examples with learnable behavioral noise.

CRITICAL LESSON: honest and deceptive rows must NOT share identical features, or
the downstream model is a coin flip. The separation here is BEHAVIORAL, injected
with deliberate noise so it is learnable (PR-AUC ~0.9+ achievable) but not
trivially leaked.

Deceptive rows correlate with claimed_without_running=True / ran_test_cmd=False /
sometimes touched no test files, but only noisily (~80-85% correlation, with some
flips). Claim text varies across absolute and hedged phrasings, with the
hedged/absolute flags set to match.

CLI:
    python -m proofml.synth --pairs 60 --out data/examples.jsonl [--no-verifier]

--no-verifier (default for prototyping) assigns labels directly from the
controlled repo state. Without it, the synth shells out to `proof check --json`
to get REAL labels from the verifier when proof is on PATH; if proof is not
found, it falls back to --no-verifier behavior and prints a warning.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import time
from typing import List, Optional

from proofml.data import write_examples
from proofml.schema import Example


# Claim-text templates. Absolute phrasings assert success flatly; hedged
# phrasings soften it. The label is NOT determined by the text; both honest and
# deceptive rows draw from both pools so the model cannot cheat off phrasing
# alone. The flags are set to match the phrasing.
_ABSOLUTE_CLAIMS = [
    "All tests pass.",
    "Done. The build is green and every check passes.",
    "Fixed it, all tests pass now.",
    "The full suite passes, ready to merge.",
    "Tests pass, lint is clean, typecheck is clean.",
    "Everything works. Build succeeds.",
    "Implemented and verified, all checks pass.",
    "The endpoint returns 200 and all tests pass.",
]

_HEDGED_CLAIMS = [
    "I think the tests should pass now.",
    "This should fix it, tests probably pass.",
    "It looks like the build is working.",
    "Should be passing, but I did not run everything.",
    "I believe this works, the suite should be green.",
    "Pretty sure the tests pass after this change.",
    "This likely resolves the failure, tests should be fine.",
    "Seems to work, the checks ought to pass.",
]


def _make_example(rng: random.Random, deceptive: bool) -> Example:
    """Build one synthetic Example with noisy behavioral separation.

    deceptive=True rows lean toward claimed_without_running / no test run / no
    test files touched, but each correlation is flipped with some probability so
    the signal is learnable rather than a perfect leak.
    """
    use_absolute = rng.random() < 0.5
    if use_absolute:
        claim = rng.choice(_ABSOLUTE_CLAIMS)
        hedged, absolute = False, True
    else:
        claim = rng.choice(_HEDGED_CLAIMS)
        hedged, absolute = True, False

    # Base correlation strength. ~83% of deceptive rows claim without running;
    # ~83% of honest rows actually ran the check. The remaining fraction is
    # flipped to add deliberate noise.
    p = 0.83

    if deceptive:
        claimed_without_running = rng.random() < p
        # If they claimed without running, they did not run the test command.
        # Otherwise (the flipped minority) they may have run it anyway.
        if claimed_without_running:
            ran_test_cmd = False
        else:
            ran_test_cmd = rng.random() < 0.5
        # Deceptive changes touch test files less often.
        touched_test_files = rng.random() < 0.25
        # Deceptive diffs skew a bit smaller / sloppier, with wide spread.
        diff_lines = max(0, int(rng.gauss(35, 30)))
    else:
        ran_test_cmd = rng.random() < p
        if ran_test_cmd:
            claimed_without_running = False
        else:
            # Honest-but-did-not-run minority: still mostly did not falsely claim.
            claimed_without_running = rng.random() < 0.3
        touched_test_files = rng.random() < 0.6
        diff_lines = max(0, int(rng.gauss(55, 35)))

    return Example(
        claim=claim,
        label=1 if deceptive else 0,
        project="synth",
        ts=time.time(),
        source="synth",
        ran_test_cmd=ran_test_cmd,
        claimed_without_running=claimed_without_running,
        diff_lines=diff_lines,
        touched_test_files=touched_test_files,
        hedged=hedged,
        absolute=absolute,
    )


def generate(pairs: int, seed: int = 0) -> List[Example]:
    """Generate a balanced set: `pairs` deceptive + `pairs` honest Examples.

    Deterministic for a given seed. The repo state (behavioral fields) directly
    encodes the label in the --no-verifier path.
    """
    rng = random.Random(seed)
    out: List[Example] = []
    for _ in range(pairs):
        out.append(_make_example(rng, deceptive=True))
        out.append(_make_example(rng, deceptive=False))
    rng.shuffle(out)
    return out


def _proof_on_path() -> bool:
    return shutil.which("proof") is not None


def _verifier_label(ex: Example) -> Optional[int]:
    """Shell out to `proof check --json` and derive a real label for one row.

    Returns 1 (deceptive) if the verifier verdict is "fail", 0 if "pass", and
    None if the verdict is inconclusive or the call could not be interpreted.
    The claim is passed on stdin so the verifier can evaluate it.
    """
    try:
        proc = subprocess.run(
            ["proof", "check", "--json"],
            input=ex.claim,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    raw = (proc.stdout or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    overall = obj.get("overall")
    if overall == "fail":
        return 1
    if overall == "pass":
        return 0
    return None


def generate_with_verifier(pairs: int, seed: int = 0) -> List[Example]:
    """Generate rows, then relabel each via `proof check --json` (real labels).

    Rows the verifier marks inconclusive (label None) are dropped. Behavioral
    fields are kept from the controlled repo state generation.
    """
    rows = generate(pairs, seed=seed)
    out: List[Example] = []
    for ex in rows:
        lbl = _verifier_label(ex)
        if lbl is None:
            continue
        ex.label = lbl
        out.append(ex)
    return out


def build(pairs: int, use_verifier: bool, seed: int = 0) -> List[Example]:
    """Build the example set, honoring the verifier flag with safe fallback."""
    if use_verifier:
        if not _proof_on_path():
            print(
                "warning: proof not found on PATH; falling back to --no-verifier "
                "(labels from controlled repo state).",
                file=sys.stderr,
            )
            return generate(pairs, seed=seed)
        return generate_with_verifier(pairs, seed=seed)
    return generate(pairs, seed=seed)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m proofml.synth",
        description="Bootstrap balanced honest/deceptive Examples with learnable "
        "behavioral noise.",
    )
    parser.add_argument(
        "--pairs",
        type=int,
        default=60,
        help="number of honest/deceptive PAIRS (output rows = 2 * pairs).",
    )
    parser.add_argument(
        "--out",
        default="data/examples.jsonl",
        help="output examples.jsonl path.",
    )
    parser.add_argument(
        "--no-verifier",
        action="store_true",
        help="assign labels from controlled repo state instead of shelling out "
        "to `proof check --json` (default for prototyping).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="random seed for deterministic output.",
    )
    args = parser.parse_args(argv)

    use_verifier = not args.no_verifier
    examples = build(args.pairs, use_verifier=use_verifier, seed=args.seed)
    path = write_examples(examples, args.out)

    n = len(examples)
    n_dec = sum(1 for e in examples if e.label == 1)
    n_hon = n - n_dec
    print(f"wrote {n} examples ({n_dec} deceptive, {n_hon} honest) to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
