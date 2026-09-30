# Configuration Reference (.proof.toml)

Place a `.proof.toml` file in your project root to override auto-detection and
tune Proof's behavior. All keys are optional; omitting a key restores the default.

## Full example

```toml
[commands]
test      = "pytest -x -q"
build     = "npm run build"
typecheck = "mypy src --strict"
lint      = "ruff check ."

[http]
base_url = "http://localhost:3000"
serve    = "npm run dev"

[verify]
max_fix_cycles  = 5
inline_budget   = 90
command_timeout = 600

[baseline]
enabled = true

[tamper]
enabled = true
disable = ["test-removed"]

[repro]
command = "pytest tests/test_regression.py -q"
```

---

## [commands]

Override the command run when a claim of the matching type is verified.
The value is a shell command string; Proof runs it directly (no shell
expansion). Set it when auto-detection picks the wrong runner or the project
uses a non-standard test invocation.

### commands.test (alias: commands.tests)

Overrides the auto-detected test runner for claims like "tests pass".

- **Type:** string (shell command)
- **Default:** auto-detect from repo files (see verifier-strategies.md for
  full detection order)
- **Alias:** `tests` (plural) is accepted as well; `test` (singular) takes
  priority when both are set

Example:
```toml
[commands]
test = "pytest -x -q --tb=short"
```

### commands.build

Overrides the auto-detected build command for claims like "the build is clean".

- **Type:** string (shell command)
- **Default:** auto-detect from repo files

Example:
```toml
[commands]
build = "cargo build --release -q"
```

### commands.typecheck

Sets the typecheck command for claims like "types check" or "type-check". There
is no auto-detection for this strategy; without this key the result is always
INCONCLUSIVE.

- **Type:** string (shell command)
- **Default:** none

Example:
```toml
[commands]
typecheck = "tsc --noEmit"
```

### commands.lint

Sets the lint command for claims like "linting passes" or "lint clean". There is
no auto-detection for this strategy; without this key the result is always
INCONCLUSIVE.

- **Type:** string (shell command)
- **Default:** none

Example:
```toml
[commands]
lint = "eslint src --max-warnings 0"
```

---

## [http]

Controls HTTP endpoint verification behavior.

### http.base_url

The base URL to use when an HTTP claim contains no URL. When an agent says
"the health endpoint returns 200" without specifying a URL, Proof uses this
value to construct the request.

- **Type:** string (URL)
- **Default:** none (INCONCLUSIVE if no URL is in the claim)

Example:
```toml
[http]
base_url = "http://localhost:8080"
```

### http.serve

Shell command to boot a local development server when an HTTP claim references
a local URL that is not currently reachable. When this is set it takes priority
over the automatic discovery of `package.json` dev/start scripts and `Procfile`
`web:` lines.

- **Type:** string (shell command)
- **Default:** auto-discover from `package.json` `scripts.dev` or `scripts.start`,
  then `Procfile` `web:` line; INCONCLUSIVE if none found

Example:
```toml
[http]
serve = "uvicorn app.main:app --port 3000"
```

---

## [verify]

Controls inline verification in the Stop hook and the fix loop.

### verify.max_fix_cycles

Maximum number of blocks in one continuation chain. A chain starts when the
agent stops on its own and continues for as long as Proof keeps blocking it.
Every block counts: a FAIL receipt, a SUSPECT block, a subagent directive, and a
"verification was not run" re-block. Once the chain reaches this many blocks,
Proof lets the turn end so the agent is never stuck in an infinite loop, and shows
the user the last verdict (a FAIL or SUSPECT with its receipts, or a note that a
pending claim was never verified). The same cap applies per claim: a claim that has been blocked this many times in the
session is not blocked again. A passing verdict ends the loop immediately.

- **Type:** integer
- **Default:** `3`

Example:
```toml
[verify]
max_fix_cycles = 2
```

### verify.inline_budget

Seconds the Stop hook spends running checks in-process before it gives up on
the rest. Checks that have not started when the budget runs out, and commands
that hit the remaining budget as their timeout, become deferred (never FAIL).
Deferred checks are handed to a verifier subagent. The red-green run needs at
least 10 seconds of remaining budget, otherwise it is deferred too.

`proof arm` sets the Stop hook's `timeout` to `inline_budget + 30` seconds, so
re-run `arm` after changing this key.

- **Type:** number (seconds)
- **Default:** `90`
- **Environment override:** `PROOF_INLINE_BUDGET` (takes precedence over the
  file when set; an unparseable value falls back to 90)

Example:
```toml
[verify]
inline_budget = 45
```

### verify.command_timeout

Per-command timeout, in seconds, for `proof verify` and `proof check`. These
run outside the hook with no shared budget, so this is the only cap on a single
command. It covers the claim's checks and both red-green repro runs (baseline
and current tree). A command that times out yields a deferred result, which
counts as INCONCLUSIVE, never FAIL. Inside the Stop hook each command is capped
by the smaller of this value and the remaining `inline_budget`.

The verifier subagent runs `proof verify` with the Bash tool's maximum timeout
(600000 ms, which is 600 seconds). Keep this value small enough that every check
of one claim finishes inside that window.

- **Type:** integer (seconds)
- **Default:** `600`

Example:
```toml
[verify]
command_timeout = 300
```

---

## [baseline]

### baseline.enabled

Whether the SessionStart hook captures a git baseline for the session. The
baseline is a commit of the full working tree (tracked and untracked files,
minus anything git ignores), written with a temporary index under
`refs/proof/baseline/<session>`. Refs and records older than 7 days are pruned
on the next capture. Your index and working tree are never modified. The
baseline commits hold copies of untracked files and appear in `git log --all`
(and in tools that list every ref) until they are pruned.

When disabled, or when Proof is armed mid-session, the diff analyzers fall
back to `HEAD` and the report notes "baseline: HEAD (approximate)". Scope and
red-green checks are skipped on an approximate baseline; tamper rules still
run. Outside a git repository all three analyzers are skipped with a note.

- **Type:** boolean
- **Default:** `true`

Example:
```toml
[baseline]
enabled = false
```

---

## [tamper]

Tamper rules look at the diff since the baseline for signs that tests were
gamed. They run when the claim includes a tests or build check. A hit makes
the verdict SUSPECT. See `verifier-strategies.md` for what each rule matches.

### tamper.enabled

- **Type:** boolean
- **Default:** `true`

Set to `false` to turn every tamper rule off.

### tamper.disable

Rule ids to turn off individually.

- **Type:** list of strings
- **Default:** `[]`
- **Rule ids:** `test-file-deleted`, `test-removed`, `skip-added`,
  `only-added`, `assert-gutted`, `runner-neutered`

Example:
```toml
[tamper]
disable = ["test-removed", "assert-gutted"]
```

---

## [repro]

### repro.command

An explicit repro command for fix claims ("I fixed the bug"). Red-green runs it
on the session baseline, where it must fail, and on the current tree, where it
must pass. It is the second repro source: test files added or modified in the
change win when the runner can target them (pytest, go test, and JS runners
such as jest and vitest), and
a ``Repro: `<command>` `` line in the claim message is the fallback.

- **Type:** string (shell command, run without a shell)
- **Default:** `""` (unset)

Example:
```toml
[repro]
command = "python -m pytest tests/test_issue_142.py -q"
```

---

## Environment variables

| Variable | Effect |
|---|---|
| `PROOF_INLINE_BUDGET` | Overrides `[verify].inline_budget` for the Stop hook and for the timeout `proof arm` writes. |
| `PROOF_HOME` | Where Proof keeps its marker store, ledger, baseline records, and temporary worktrees. Default `~/.proof`. |

---

## Precedence

For `[commands]` strategies, the resolution order is:

1. A command carried by the claim itself. Claims extracted from message text
   never carry one for these strategies, so in practice this applies only when
   a strategy is called directly through the Python API.
2. `.proof.toml` `[commands]` key for the strategy (always checked before
   auto-detection).
3. Auto-detection from repo files.

For `[http]`, the serve command resolution order is:

1. `.proof.toml` `[http].serve`.
2. `package.json` `scripts.dev`, then `scripts.start`.
3. `Procfile` `web:` line.

For the red-green repro, the resolution order is:

1. Test files added or modified since the baseline, run through the targeted
   test runner.
2. `.proof.toml` `[repro].command`.
3. A ``Repro: `<command>` `` line in the claim message.
