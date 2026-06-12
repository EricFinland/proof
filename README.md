# Proof

[![tests](https://github.com/EricFinland/proof/actions/workflows/ci.yml/badge.svg)](https://github.com/EricFinland/proof/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)

**Your coding agent can no longer say "done" without receipts.**

Proof is a [Claude Code](https://docs.claude.com/en/docs/claude-code) skill plus
Stop hook that auto-fact-checks an agent's completion claims. The moment the
agent says "tests pass" or "all done, it works", Proof fires an *independent*
verifier that runs the real checks and returns a strict
**PASS / FAIL / INCONCLUSIVE** verdict with the actual command output as evidence,
before the turn is allowed to end.

No configuration. No success criteria to write. Arm it once, then work normally.

![Proof catching a false completion claim](assets/demo.gif)

## See it catch a lie

A repository whose tests are red. The agent claims they are green. Proof runs the
test suite itself and busts the claim:

```
1. The agent ends its turn with a claim:
   "All done, tests pass."

2. The Stop hook fires automatically and injects the verifier directive:
   decision: block
   reason:  PROOF: you just claimed work is complete. Do NOT stop. Spawn an
            INDEPENDENT verifier subagent that runs the real checks ...

3. The independent verifier runs the REAL check:
   FAIL
     FAIL tests: `python -m pytest -q`
   exit code: 1
```

And the receipt it writes to `proof-report.md`:

```
# Proof Report -- FAIL

## FAIL -- tests
- Claim:   All done, tests pass.
- Command: `python -m pytest -q`

    >   assert 1 == 2
    E   assert 1 == 2
    FAILED test_bad.py::test_bad - assert 1 == 2
    1 failed in 0.05s
```

### Caught in a real repo

This is not a contrived fixture. Pointed at a real project whose test
environment was silently broken, Proof caught that "all tests pass" was false:
the suite did not even import.

```
$ proof verify --transcript turn.jsonl --root .
FAIL
  FAIL tests: `python -m pytest -q`

  ERROR collecting tests/test_cli.py
  E   ModuleNotFoundError: No module named 'mcp_audit'
  exit code: 1
```

An agent that said "done, tests pass" there would have been wrong, and you would
have found out three steps later. Proof finds out immediately.

## Why this matters

Hallucinated completion is the biggest trust gap in agentic coding. The agent
grades its own homework, so "it works" is unreliable, and you find out by hand.
Proof breaks the loop: a separate verifier, in a fresh context, assumes every
claim may be false and trusts only execution output. One failed check fails the
whole turn.

## Install

One line, via the [skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add EricFinland/proof
```

Or grab it directly and arm the hook yourself:

```bash
cd <your project>
python /path/to/proof/scripts/proof.py arm
```

Arming adds a `Stop` hook to your project's `.claude/settings.json`. Then work
as usual. Turn it off any time:

```bash
python /path/to/proof/scripts/proof.py disarm   # remove the hook
python /path/to/proof/scripts/proof.py status   # armed | disarmed
```

Run a check manually against any transcript:

```bash
python proof/scripts/proof.py verify --transcript <path> --root <repo>
# exit 0 = PASS, 1 = FAIL, 2 = INCONCLUSIVE
```

## How it works

1. The Stop hook (`proof_trigger.py`) reads Claude Code's hook payload and pulls
   the agent's last message.
2. A precision classifier checks it for completion-claim language. It is tuned
   against real-world traps ("I fixed a typo", "the done button is broken",
   "should work eventually") so it does not cry wolf.
3. On a fresh claim, the hook blocks the stop and injects a directive telling the
   agent to spawn an independent verifier subagent.
4. The verifier extracts the checkable assertions, runs the matching strategy,
   aggregates a strict verdict, and writes `proof-report.md`.
5. A per-session fix loop re-blocks after a FAIL (up to `max_fix_cycles`, default
   3). After a PASS or INCONCLUSIVE the claim is never re-blocked. If the limit
   is reached without a pass, Proof gives up silently rather than nagging forever.
   On re-block, the previous `proof-report.md` is prepended as "PREVIOUS RECEIPTS"
   and the directive notes "attempt N of MAX".

## Verifier strategies

Proof maps each claim to a deterministic check. Missing tooling yields
INCONCLUSIVE, never a false PASS.

| Strategy | Verifies a claim like |
|----------|-----------------------|
| `tests` | "tests pass" (auto-detects runner by repo files) |
| `build` | "the build is clean" |
| `typecheck` | "types check" |
| `lint` | "lint is clean" |
| `command` | "running X works" |
| `http` | "GET /health returns 200", body assertions, boots local servers, verifies live deploy URLs |
| `repro` | "the bug is fixed" (re-runs the original repro) |
| `filecheck` | "added function X to file Y" |

## Runner support

Test and build runner auto-detection covers: Node/Bun/pnpm/yarn/npm
(by lockfile), Python/pytest, Rust/Cargo, Go, Maven, Gradle (wrapper preferred),
.NET (sln/csproj), Make (when a `test:` target exists), Elixir/Mix, PHP/Composer.

## HTTP verification (v2)

The `http` strategy handles three scenarios:

1. **Live URL in claim.** Makes an HTTP GET and checks the status code. Non-local
   URLs that are unreachable are treated as a failed deploy claim (FAIL, not
   INCONCLUSIVE).
2. **Local URL, server not running.** Boots a local server automatically using
   (in order): `[http].serve` from `.proof.toml`, then `package.json` `dev`/`start`
   script, then `Procfile` `web:` line. Polls for readiness up to 30 seconds,
   then tears down the process tree.
3. **Body assertion.** Claims containing `with "..."` or `containing "..."` (e.g.,
   `GET /health returns 200 with "ok"`) also check that the response body contains
   the expected substring.

## Fix loop

When verification fails, Proof does not let the agent walk away. It re-blocks
the turn with the previous `proof-report.md` receipts and a note reading
"attempt N of MAX". After `max_fix_cycles` failed attempts (default 3, override
in `.proof.toml`), Proof stops blocking so you are not stuck in an infinite
loop. A passing verdict clears the loop immediately.

## proof stats

Track the agent's honesty over time. Every `proof verify` run appends an entry
to `~/.proof/ledger.jsonl` (override with `PROOF_HOME`).

```
$ proof stats
Honesty rate: 72% (18 verified, 5 lies caught)
Clean streak: 4
Worst offender: tests (3 catches)
Last catch: "All done, tests pass." (2026-06-10)
```

Filter to recent runs:

```
$ proof stats --days 7
```

Machine-readable output for CI pipelines:

```
$ proof stats --json
```

## Works with any agent

`proof check` verifies any claim text directly, without a transcript. Works from
CI or with any coding agent:

```bash
proof check "all tests pass and the build is clean" --root /repo --json
# exit 0 = PASS, 1 = FAIL, 2 = INCONCLUSIVE
```

The `--json` flag emits a single JSON object with keys `overall`, `exit`,
`results`, and `report`. Pipe it into any CI assertion or notification webhook.

## .proof.toml reference

Place `.proof.toml` in your project root to override auto-detection.

| Key | What it does | Default |
|-----|-------------|---------|
| `[commands].test` | Test command used instead of auto-detected runner (singular key; `tests` is also accepted) | auto-detect |
| `[commands].build` | Build command used instead of auto-detected runner | auto-detect |
| `[commands].typecheck` | Typecheck command (no auto-detect; required to get a non-inconclusive verdict) | none |
| `[commands].lint` | Lint command (no auto-detect; required to get a non-inconclusive verdict) | none |
| `[http].base_url` | Base URL used for HTTP claims that contain no URL | none |
| `[http].serve` | Shell command to boot a local server for HTTP verification | auto-detect |
| `[verify].max_fix_cycles` | Maximum number of re-verification attempts before Proof stops blocking | `3` |

Example:

```toml
[commands]
test = "pytest -x -q"
lint = "ruff check ."
typecheck = "mypy src"

[http]
base_url = "http://localhost:3000"
serve = "npm run dev"

[verify]
max_fix_cycles = 5
```

## Design

- **Pure Python standard library.** No dependencies. Runs anywhere Python 3.11+ runs.
- **Adversarial by construction.** The verifier is told to distrust the claims and
  accept only execution artifacts.
- **Strict aggregation.** Any single failed claim fails the entire verdict.
- **Cross-platform.** Tested on Linux and Windows in CI.

Full design and contract docs live in
[`proof/references/`](proof/references). The skill manifest is
[`proof/SKILL.md`](proof/SKILL.md).

## Development

```bash
cd proof
python -m pytest -q
```

199 tests cover the classifier, claim extractor, every strategy, verdict
aggregation, the Stop hook's crash-safety and recursion guard, the ledger,
the fix loop, the installer, and an end-to-end acceptance test that reproduces
the demo above.

## License

MIT. See [LICENSE](LICENSE).
