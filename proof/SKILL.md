---
name: proof
description: Use when an agent claims work is complete ("tests pass", "it works", "deployed") and you want it auto-verified. Catches hallucinated completion by spawning an independent verifier that runs the real checks and returns PASS/FAIL/INCONCLUSIVE with receipts. Arm once per project; the Stop hook fires automatically on every completion claim.
---

# Proof -- fact-check completion claims

Proof arms a Stop hook that fires whenever Claude asserts a task is done. An
independent verifier subagent then runs the real checks (tests, build, endpoints,
repro) and returns a strict verdict with receipts. The agent can no longer
self-certify.

## Arm / disarm

- Arm (per project): `python scripts/proof.py arm`
- Disarm: `python scripts/proof.py disarm`
- Status: `python scripts/proof.py status`

All three commands accept `--settings <path>` to target a specific
`settings.json` (defaults to `.claude/settings.json` in the current directory).

## Manual verify

```
python scripts/proof.py verify --transcript <path> --root <repo>
```

Reads the last assistant message from `<transcript>`, extracts claims, runs
the matching verifier strategies against `<repo>`, writes `proof-report.md` in
the current directory, prints the verdict to stdout, and exits:

- 0 -- PASS
- 1 -- FAIL
- 2 -- INCONCLUSIVE

## How it works

1. The Stop hook (`scripts/proof_trigger.py`) reads Claude Code's hook payload
   from stdin. If the last assistant message contains a completion claim and has
   not already been verified this session, it blocks the turn and injects a
   directive for the agent to spawn an independent verifier subagent.
2. The verifier subagent follows `references/verifier-subagent.md`: it assumes
   all claims may be false, runs `proof.py verify`, and reports the verdict.
3. The deterministic Python core extracts claims, dispatches them to verifier
   strategies, aggregates results (any FAIL -> overall FAIL), and writes
   `proof-report.md` with the command output receipt for every check.

## Check (agent-agnostic verification)

Verify any claim text directly, without a transcript. Works with any coding
agent or from CI:

```
python scripts/proof.py check "all tests pass and the build is clean" --root <repo>
```

Exit codes are the same as `verify`: 0 = PASS, 1 = FAIL, 2 = INCONCLUSIVE.
Add `--json` for machine-readable output (keys: `overall`, `exit`, `results`,
`report`). See `references/evidence-format.md` for the full JSON schema.

## Stats (honesty ledger)

Every `proof verify` run appends an entry to `~/.proof/ledger.jsonl` (override
with `PROOF_HOME`). View aggregate stats:

```
python scripts/proof.py stats           # human-readable
python scripts/proof.py stats --days 7  # last 7 days only
python scripts/proof.py stats --json    # machine-readable
```

Sample output:

```
Honesty rate: 72% (18 verified, 5 lies caught)
Clean streak: 4
Worst offender: tests (3 catches)
Last catch: "All done, tests pass." (2026-06-10)
```

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
max_fix_cycles = 5
```

See `references/configuration.md` for every key, its default, and precedence
rules.

## References

- `references/hook-setup.md` -- Stop hook wiring, blocking policy, recursion guard
- `references/verifier-subagent.md` -- adversarial verifier subagent prompt
- `references/verifier-strategies.md` -- per-strategy detection and verdict rules
- `references/evidence-format.md` -- proof-report.md layout, exit-code mapping, --json schema
- `references/configuration.md` -- .proof.toml full reference
