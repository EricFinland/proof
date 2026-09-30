# <img src="../assets/logo.svg" alt="" width="36" align="top"> Proof (v3.0.0)

Proof is a Claude Code skill plus Stop hook that auto-fact-checks completion
claims made by the agent. When the agent says "tests pass" or "all done, it
works", the hook runs the real checks itself, diffs the tree against where the
session started, and returns a strict PASS / FAIL / SUSPECT / INCONCLUSIVE
verdict with receipts before the turn is allowed to end.

v3 adds: checks run inside the hook, SUSPECT for gamed tests, red-green receipts
for fix claims, claim-vs-diff checks, pending enforcement so a verification
cannot be skipped by stopping again, and `--since` for CI.

## The trust problem

The agent grades its own work, so self-reported success is unreliable. Worse,
an agent under pressure to go green can make the tests pass without making the
code work: skip the failing test, delete it, or rig the test command. Proof
trusts only commands it ran and a diff it computed.

## Verdicts and exit codes

| Verdict | Exit | Meaning |
|---|---|---|
| PASS | 0 | Every check ran and passed, and nothing in the diff undermines it. |
| FAIL | 1 | A check failed. The receipt is the command and its output. |
| INCONCLUSIVE | 2 | Nothing could be checked definitively. |
| SUSPECT | 3 | The checks pass, but the tests were gamed, the fix was never red, or the claim contradicts the diff. |

Any FAIL fails the whole verdict. A SUSPECT finding outranks any number of
passes.

## How it works

1. **SessionStart** (`scripts/proof_session_start.py`) snapshots the working
   tree into `refs/proof/baseline/<session>` with a temporary index. Your index
   and working tree are never touched.
2. **Stop** (`scripts/proof_trigger.py`) detects a completion claim and runs the
   checks in-process under `[verify].inline_budget` seconds (default 90), then
   the diff analyzers: tamper rules, scope checks, and red-green for fix claims.
3. FAIL blocks with the receipt inline. SUSPECT blocks once with the findings,
   then goes to the user as a message if they remain. PASS lets the turn end.
4. Checks that did not finish, or came back INCONCLUSIVE, are marked pending and
   handed to an independent verifier subagent (`references/verifier-subagent.md`).
   If the agent stops again without running `proof.py verify --claim-key ...`,
   the hook blocks again. Every block in one chain counts toward
   `[verify].max_fix_cycles` (default 3), so it never loops forever.

## Usage

```
python scripts/proof.py arm        # install the SessionStart and Stop hooks
python scripts/proof.py disarm     # remove both
python scripts/proof.py status     # armed | disarmed (or the v2 upgrade hint)

python scripts/proof.py verify --transcript <path.jsonl> --root <repo>
python scripts/proof.py check "all tests pass" --root <repo> --since origin/main
python scripts/proof.py stats [--days 7] [--json]
```

`verify` and `check` write `proof-report.md`, print the verdict, and exit with
the codes above. Both accept `--json` and `--since <ref>`; `verify` also takes
`--session`, `--claim-key`, and `--out-dir`.

**Upgrading from v2:** run `proof arm` again in each project. A v2 Stop hook
still works, but without the SessionStart hook (approximate baselines) and
without a hook timeout. `proof status` prints
`armed (v2 hook entry: run "proof arm" again to upgrade)` until you re-arm.

## Quick demo

```
python scripts/proof.py check "all tests pass" --root tests/fixtures/tests_fail
```

prints `FAIL` with the failing pytest command and exits 1. See
`tests/test_end_to_end.py` for the full hook-to-verdict flow.

## More

- `SKILL.md` -- the skill manifest and command reference
- `references/hook-setup.md` -- both hooks, pending enforcement, chain cap
- `references/verifier-subagent.md` -- the adversarial verifier prompt
- `references/verifier-strategies.md` -- strategies, tamper rules, scope rules, red-green verdicts
- `references/evidence-format.md` -- proof-report.md layout, exit codes, --json schema
- `references/configuration.md` -- .proof.toml full reference

## Requirements

Python 3.11+, stdlib only. No external dependencies. git is needed for the
baseline and diff checks. pytest is required only for running the test suite.
