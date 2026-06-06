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

## References

- `references/hook-setup.md` -- Stop hook wiring and recursion guard
- `references/verifier-subagent.md` -- adversarial verifier subagent prompt
- `references/verifier-strategies.md` -- per-strategy detection and verdict rules
- `references/evidence-format.md` -- proof-report.md layout and exit-code mapping
