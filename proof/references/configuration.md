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
max_fix_cycles = 5
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

Controls the fix loop and re-verification behavior.

### verify.max_fix_cycles

Maximum number of times Proof will block a turn and demand re-verification for
the same claim within one session. After this many failed attempts, Proof stops
blocking so the agent is not stuck in an infinite loop. A passing verdict always
clears the loop immediately, regardless of this setting.

- **Type:** integer
- **Default:** `3`

Example:
```toml
[verify]
max_fix_cycles = 2
```

---

## Precedence

For `[commands]` strategies, the resolution order is:

1. Explicit `command=` supplied by the claim extractor (rare; reserved for
   strategies like `command`, `repro`, `filecheck` that extract a command from
   the claim text directly).
2. `.proof.toml` `[commands]` key for the strategy (always checked before
   auto-detection).
3. Auto-detection from repo files.

For `[http]`, the serve command resolution order is:

1. `.proof.toml` `[http].serve`.
2. `package.json` `scripts.dev`, then `scripts.start`.
3. `Procfile` `web:` line.
