# Verifier Strategies

Each strategy is a Python function with the signature:

```python
def verify_*(claim, root, command=None, expectation=None) -> Result
```

`Result` fields: `claim`, `method`, `command`, `raw_output`, `verdict` (one of
`pass`/`fail`/`inconclusive`), `confidence` (float, default 1.0).

---

## tests

**Detection:** triggered when the claim contains phrases like "tests pass",
"all tests pass", or similar (matched by the extractor's regex).

**Execution:** calls `detect_test_cmd(root)` to auto-detect the test runner from
repo files. A command set in `.proof.toml` `[commands].test` (or `.tests`)
takes precedence over auto-detection. Detection order when no config command is
set:

1. `package.json` with a `test` script. Package manager chosen by lockfile:
   `bun.lockb`/`bun.lock` -> `bun run test`; `pnpm-lock.yaml` -> `pnpm run test`;
   `yarn.lock` -> `yarn run test`; else `npm test --silent`.
2. `pyproject.toml`, `pytest.ini`, or a `tests/` directory -> `python -m pytest -q`.
3. `Cargo.toml` -> `cargo test -q`.
4. `go.mod` -> `go test ./...`.
5. `pom.xml` -> `mvn -q test`.
6. `build.gradle` / `build.gradle.kts` / `gradlew` / `gradlew.bat` -> Gradle
   wrapper (`gradlew test` or `gradlew.bat test`) if present, else `gradle test`.
7. `*.sln` or `*.csproj` -> `dotnet test`.
8. `Makefile` with a `test:` target -> `make test`.
9. `mix.exs` -> `mix test`.
10. `composer.json` with a `scripts.test` key -> `composer test`.

If a `command` argument is supplied directly it is used instead of all of the
above, split on whitespace.

**Verdict rules:**
- PASS -- command exits 0
- FAIL -- command exits non-zero (any value other than 0 or 127)
- INCONCLUSIVE -- no test runner detected (command is None) OR command not found
  (exit code 127, e.g. `pytest` not installed); confidence 0.3

---

## build

**Detection:** triggered when the claim contains phrases like "build is clean",
"build is green", "build is passing", or "builds success".

**Execution:** calls `detect_build_cmd(root)` to auto-detect the build command.
Detection order: `package.json` with a `build` script (runs `npm run build`),
`Cargo.toml` (runs `cargo build -q`), `go.mod` (runs `go build ./...`). A
`command` argument overrides auto-detection, split on whitespace.

**Verdict rules:**
- PASS -- command exits 0
- FAIL -- command exits non-zero (any value other than 0 or 127)
- INCONCLUSIVE -- no build command detected OR command not found (exit 127);
  confidence 0.3

---

## typecheck

**Detection:** triggered when the claim mentions "typecheck" or "type-check".

**Execution:** no auto-detection; requires an explicit `command` argument (e.g.
`tsc --noEmit`), split on whitespace.

**Verdict rules:**
- PASS -- command exits 0
- FAIL -- command exits non-zero (any value other than 0 or 127)
- INCONCLUSIVE -- no command supplied OR command not found (exit 127); confidence 0.3

---

## lint

**Detection:** triggered when the claim contains "linting passes" or "lint clean".

**Execution:** no auto-detection; requires an explicit `command` argument (e.g.
`eslint .` or `ruff check .`), split on whitespace.

**Verdict rules:**
- PASS -- command exits 0
- FAIL -- command exits non-zero (any value other than 0 or 127)
- INCONCLUSIVE -- no command supplied OR command not found (exit 127); confidence 0.3

---

## command

**Detection:** triggered by claims containing a specific command the agent says
it ran successfully. The extractor passes the command string verbatim.

**Execution:** splits `command` with `shlex.split(posix=False)` and runs it.

**Verdict rules:**
- PASS -- command exits 0
- FAIL -- command exits non-zero (any value other than 0 or 127)
- INCONCLUSIVE -- no command given OR command not found (exit 127); confidence 0.2

---

## http

**Detection:** triggered when the claim contains an HTTP/HTTPS URL or phrases
like "returns 200" or "endpoint". The URL is extracted by regex; the expected
status defaults to "200".

**Execution (v2):** the strategy resolves the URL and optional body expectation
from the claim, then picks one of three execution paths:

1. **URL is reachable.** Makes an HTTP GET using `urllib.request.urlopen` with a
   10-second timeout, reads up to 2000 bytes of the response body, then
   evaluates status and (optionally) body.

2. **URL is local and connection is refused.** Boots a local server automatically.
   Serve command resolution order: `[http].serve` in `.proof.toml`, then
   `package.json` `scripts.dev` or `scripts.start`, then the first `web:` line in
   `Procfile`. The server is started in a new process group; readiness is polled
   every 0.5 s for up to 30 seconds. After the check the process tree is killed
   with `taskkill /T /F` (Windows) or `SIGTERM` to the process group (POSIX).
   Returns INCONCLUSIVE if no serve command is found or the server does not
   become ready within 30 s.

3. **URL is non-local and connection fails.** The claim asserts a deployed URL
   that is unreachable. This is treated as a failed deployment claim: FAIL with
   confidence 1.0, not INCONCLUSIVE.

**Body assertions:** if the claim contains `with "..."` or `containing "..."`,
the quoted string must appear as a substring in the response body; otherwise the
result is FAIL even if the status code matched.

**Status parsing:** a three-digit number preceded by "returns" or "status" in the
claim text sets the expected status code. Claims like "returns 404" pass when the
server actually returns 404.

**Verdict rules:**
- PASS -- status code matches AND (if a body assertion is present) the expected
  substring is found in the response body
- FAIL -- status code does not match, OR body assertion fails, OR non-local URL
  is unreachable
- INCONCLUSIVE -- no URL found in the claim (confidence 0.2), OR local server
  not running and no serve command found (confidence 0.3), OR local server did
  not become ready within 30 s (confidence 0.3)

---

## repro

**Detection:** used when the agent claims a bug is fixed by re-running the
original repro command. Requires an explicit `command` argument.

**Execution:** splits `command` with `shlex.split(posix=False)` and runs it.

**Verdict rules:**
- PASS -- command exits 0
- FAIL -- command exits non-zero (any exit code)
- INCONCLUSIVE -- no command given; confidence 0.2

Note: unlike `tests` and `command`, `repro` maps any non-zero exit to FAIL
(there is no special handling for exit code 127).

---

## filecheck

**Detection:** used when the agent claims a symbol, function, or string was
added to a file. Requires `command` (the symbol to search for) and `expectation`
(the relative file path within `root`).

**Execution:** reads the target file as text and performs a plain substring
search for the symbol.

**Verdict rules:**
- PASS -- symbol is found in the file
- FAIL -- symbol is absent from the file
- INCONCLUSIVE -- target file does not exist or `expectation` is empty;
  confidence 0.3
