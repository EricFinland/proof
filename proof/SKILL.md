---
name: proof
description: Use when an agent claims work is complete ("tests pass", "it works", "fixed") and you want it auto-verified. The Stop hook runs the real checks itself, flags gamed tests (skips, deletions, gutted asserts) as SUSPECT, proves fixes red then green, and returns PASS/FAIL/SUSPECT/INCONCLUSIVE with receipts. Arm once per project; it fires automatically on every completion claim.
---

# Proof -- fact-check completion claims

Proof arms a Stop hook that fires whenever the agent asserts a task is done. The
hook runs the real checks itself (tests, build, endpoints), checks the diff for
gamed tests, proves "fixed" claims red then green, and returns a strict verdict
with receipts. The agent can no longer self-certify.

## Arm / disarm

- Arm (per project): `python scripts/proof.py arm`
- Disarm: `python scripts/proof.py disarm`
- Status: `python scripts/proof.py status`

All three commands accept `--settings <path>` to target a specific
`settings.json` (defaults to `.claude/settings.json` in the current directory).

Arming installs two hooks:

- **SessionStart** (`scripts/proof_session_start.py`, timeout 30s) captures a
  git baseline of the working tree for the session, so later checks can diff
  against exactly what the agent started with. Disable with
  `[baseline] enabled = false`.
- **Stop** (`scripts/proof_trigger.py`, timeout `inline_budget + 30`s) detects
  completion claims and verifies them.

## Verdicts and exit codes

| Verdict | Exit | Meaning |
|---|---|---|
| PASS | 0 | No check failed or looked gamed, and at least one check passed. |
| FAIL | 1 | At least one check failed. The receipt is the command output. |
| INCONCLUSIVE | 2 | Nothing could be checked definitively. |
| SUSPECT | 3 | The checks pass, but the diff shows they were gamed (skipped or deleted tests, gutted asserts, a neutered test command), a fix that was never red, or a claim the diff contradicts. |

Severity when combining results: FAIL > SUSPECT > PASS > INCONCLUSIVE.

## Manual verify

```
python scripts/proof.py verify --transcript <path> --root <repo>
```

Reads the agent's last message from `<transcript>`, extracts claims, runs
the matching strategies and the diff analyzers against `<repo>`, writes
`proof-report.md` in the current directory (or `--out-dir`), prints the
verdict, and exits with the code above.

Flags:

- `--session <id>` records the outcome in the marker store so the Stop hook
  sees it.
- `--claim-key <key>` verifies the claim text the hook stored under that key
  instead of the transcript's last message. The hook's directive always passes
  it, because after a block the newest message is usually not the claim.
- `--since <ref>` diffs against the merge-base of that ref or commit and
  `HEAD` instead of the session baseline.
- `--json` prints one JSON object instead of ASCII lines.

## How it works

1. On SessionStart, Proof snapshots the working tree into a commit under
   `refs/proof/baseline/<session>` using a temporary index. Your index and
   working tree are never touched.
2. On Stop, a precision classifier checks the last message for a completion
   claim. On a fresh claim, the hook runs the checks in-process under
   `[verify].inline_budget` seconds (default 90).
3. The diff analyzers run against the baseline: tamper rules (on tests and
   build claims), claim-vs-diff scope checks, and red-green for fix claims.
4. The hook decides:
   - PASS: the stop is allowed with a `Proof: PASS (...)` message.
   - FAIL: the stop is blocked with the failing command and its output inline.
     No subagent is needed.
   - SUSPECT: blocked once with the findings. If the same findings come back,
     they go to the user as a message instead of a second block.
   - Checks that did not finish in the budget, or came back INCONCLUSIVE, are
     marked pending. The hook blocks with a directive to spawn an independent
     verifier subagent that follows `references/verifier-subagent.md` and runs
     `proof.py verify --session ... --claim-key ...`.
5. Pending enforcement: if the agent stops again without running that verify,
   the hook blocks again with "verification was not run". Every block in one
   continuation chain counts toward `[verify].max_fix_cycles` (default 3), so
   it can never loop forever.

When a fix claim has no repro (no changed test file, no `[repro].command`, no
`Repro:` line), the block reason asks the agent to add a line like
``Repro: `pytest tests/test_bug.py` `` that failed before the fix.

## Check (agent-agnostic verification)

Verify any claim text directly, without a transcript. Works with any coding
agent or from CI:

```
python scripts/proof.py check "all tests pass and the build is clean" --root <repo>
python scripts/proof.py check "all tests pass" --root <repo> --since origin/main
```

`--since` diffs against the merge-base of the given ref and `HEAD`, so tamper
and scope checks cover a whole branch. Exit codes are the same as `verify`. Add
`--json` for machine-readable output (keys: `overall`, `exit`, `results`, `report`; each result carries
`findings`). See `references/evidence-format.md` for the full schema.

## Stats (honesty ledger)

Every `proof verify` and `proof check` run appends an entry to
`~/.proof/ledger.jsonl` (override with `PROOF_HOME`). View aggregate stats:

```
python scripts/proof.py stats           # human-readable
python scripts/proof.py stats --days 7  # last 7 days only
python scripts/proof.py stats --json    # machine-readable
```

Sample output:

```
Honesty rate: 68% (19 verified, 6 lies caught)
Gamed: 2
Clean streak: 3
Worst offender: tests (3 catches)
Last catch: "All done, tests pass." (2026-09-28)
```

`Gamed` counts SUSPECT verdicts and only appears when there is at least one.

## Configuration (.proof.toml)

Place `.proof.toml` in the project root to override auto-detection:

```toml
[commands]
test      = "pytest -x -q"
typecheck = "mypy src"
lint      = "ruff check ."

[http]
base_url = "http://localhost:3000"
serve    = "npm run dev"

[verify]
max_fix_cycles  = 5
inline_budget   = 90    # seconds the Stop hook spends before deferring
command_timeout = 600   # per-command cap for verify and check

[baseline]
enabled = true

[tamper]
enabled = true
disable = []            # rule ids, e.g. ["test-removed"]

[repro]
command = ""            # explicit repro for fix claims
```

The environment variable `PROOF_INLINE_BUDGET` overrides `inline_budget`. See
`references/configuration.md` for every key, its default, and precedence rules.

## References

- `references/hook-setup.md` -- SessionStart and Stop hooks, pending enforcement, chain cap
- `references/verifier-subagent.md` -- adversarial verifier subagent prompt
- `references/verifier-strategies.md` -- strategies, tamper rules, scope rules, red-green verdicts
- `references/evidence-format.md` -- proof-report.md layout, exit codes, --json schema
- `references/configuration.md` -- .proof.toml full reference
