# Proof

Proof is a Claude Code skill and Stop hook that auto-fact-checks completion
claims made by the agent. When the agent says "tests pass" or "all done, it
works", Proof fires an independent verifier that runs the real checks and
returns a strict PASS/FAIL/INCONCLUSIVE verdict with receipts before the
session ends.

## The trust problem

Agents sometimes emit confident-sounding completion claims that are false.
The agent grades its own work, so self-reported success is unreliable.
Proof breaks this loop by spawning a separate verifier that assumes every
claim may be false and trusts only execution output.

## Install (arm the hook)

```
python scripts/proof.py arm
```

This adds a `Stop` hook to `.claude/settings.json` that fires
`proof_trigger.py` at the end of every turn. Remove it with:

```
python scripts/proof.py disarm
```

Check current state:

```
python scripts/proof.py status
```

## How it works

1. The Stop hook (`proof_trigger.py`) reads the Claude Code hook payload
   from stdin: `{session_id, transcript_path, stop_hook_active}`.
2. It extracts the last assistant message from the transcript and runs the
   classifier to detect a completion claim.
3. If a fresh claim is found (not already verified this session), the hook
   responds with `{"decision": "block", "reason": <verifier directive>}`,
   which prevents the session from stopping and injects a prompt that
   instructs the agent to spawn an independent verifier subagent.
4. The verifier subagent follows `references/verifier-subagent.md`. It
   treats the claim as unproven, runs `proof.py verify`, and reports the
   verdict with command output as evidence.
5. A per-session recursion guard (`~/.proof/verified.json`) ensures the
   same claim is never verified twice, preventing infinite loops.

The `stop_hook_active` field in the payload is `true` when Claude Code
itself triggered the stop (e.g., from inside the verifier run). The hook
no-ops in that case, which prevents the hook from blocking its own spawned
sub-sessions.

## Verifier strategies

Proof auto-selects strategies based on the claim text:

| Strategy    | Triggered by                                  | How it verifies                              |
|-------------|-----------------------------------------------|----------------------------------------------|
| `tests`     | "tests pass", "all tests pass"                | Runs detected test command (pytest, npm test, cargo test, go test) |
| `build`     | "build is clean/green/passing"                | Runs detected build command (npm run build, cargo build, go build) |
| `typecheck` | "typecheck", "type-check"                     | Runs supplied command (e.g. tsc --noEmit)    |
| `lint`      | "linting passes", "lint clean"                | Runs supplied command (e.g. ruff check .)    |
| `command`   | Explicit command in claim                     | Runs the extracted command, checks exit code |
| `http`      | URL in claim, "returns 200", "endpoint"       | HTTP GET, checks status code                 |
| `repro`     | Bug-fix claims with a repro command           | Re-runs the repro command, checks exit code  |
| `filecheck` | Symbol-addition claims with file + symbol     | Substring search in the target file          |

## Verify CLI

Run the verifier directly against any transcript:

```
python scripts/proof.py verify --transcript <path.jsonl> --root <repo_dir>
```

Output:
- Prints the verdict to stdout: `PASS`, `FAIL`, or `INCONCLUSIVE`
- Writes `proof-report.md` in the current directory with one section per
  strategy run: verdict, command, and captured output (up to 3000 chars)
- Exit codes: `0` = PASS, `1` = FAIL, `2` = INCONCLUSIVE

Verdict aggregation rule: any single FAIL makes the overall verdict FAIL.
All strategies must pass for the overall verdict to be PASS. If no strategy
fires or all are inconclusive, the verdict is INCONCLUSIVE.

## ASCII verdict markers

The CLI and report use ASCII-safe markers to avoid encoding issues on
Windows terminals:

- `PASS`
- `FAIL`
- `INCONCLUSIVE`

## 10-second demo

1. `cd proof/tests/fixtures/tests_fail`
2. Ask Claude to "make the tests pass," then have it say "all done, tests pass."
3. With Proof armed, the Stop hook fires the verifier, which runs pytest and
   reports: FAIL -- you said tests pass; 1 failed. See proof-report.md.

Or run it directly:

```
python scripts/proof.py verify \
  --transcript tests/fixtures/tests_fail/transcript.jsonl \
  --root tests/fixtures/tests_fail
```

(Create a minimal transcript JSONL with a false claim; see
`tests/test_end_to_end.py` for a programmatic example.)

## References

- `references/hook-setup.md` -- hook wiring, recursion guard details
- `references/verifier-subagent.md` -- the adversarial verifier prompt
- `references/verifier-strategies.md` -- per-strategy detection and verdict rules
- `references/evidence-format.md` -- proof-report.md layout and exit-code mapping

## Requirements

Python 3.11+, stdlib only. No external dependencies. pytest required only
for running the test suite.
