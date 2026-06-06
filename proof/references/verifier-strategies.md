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
repo files. Detection order: `package.json` with a `test` script (runs
`npm test --silent`), `pyproject.toml` / `pytest.ini` / `tests/` directory
(runs `python -m pytest -q`), `Cargo.toml` (runs `cargo test -q`), `go.mod`
(runs `go test ./...`). If a `command` argument is supplied it is used instead,
split on whitespace.

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

**Execution:** makes an HTTP GET to the URL using `urllib.request.urlopen` with
a 10-second timeout. Reads up to 2000 bytes of the response body.

**Verdict rules:**
- PASS -- actual HTTP status code matches the expected status (string comparison)
- FAIL -- status code does not match, OR the request raises an exception
  (connection refused, DNS failure, etc.)
- INCONCLUSIVE -- no URL in the claim; confidence 0.2

Note: non-2xx responses that raise `urllib.error.HTTPError` are caught and
their status codes are compared against the expectation, so a claim of "returns
404" would pass if the server returns 404.

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
