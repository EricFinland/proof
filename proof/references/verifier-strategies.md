# Verifier Strategies

Proof checks a claim in two ways:

- **Strategies** run a command (or an HTTP request) for each checkable phrase in
  the claim: `tests`, `build`, `typecheck`, `lint`, `http`.
- **Diff analyzers** look at what changed since the session baseline:
  `tamper` (were the tests gamed?), `scope` (does the claim match the diff?),
  and `redgreen` (was the fix ever red?). These are what produce SUSPECT.

Each strategy is a Python function with the signature:

```python
def verify_*(claim, root, command=None, expectation=None, timeout=None) -> Result
```

`Result` fields: `claim`, `method`, `command`, `raw_output`, `verdict` (one of
`pass`/`fail`/`suspect`/`inconclusive`/`deferred`), `confidence` (float,
default 1.0), `findings` (list, empty unless SUSPECT).

Every command-running strategy shares these rules:

- Commands are split with POSIX quoting rules (quoted arguments survive; on
  Windows lone backslashes are preserved) and run without a shell.
- Exit 0 is PASS. Exit 127 or a missing executable is INCONCLUSIVE. Any other
  non-zero exit is FAIL.
- A command that hits its timeout is `deferred`, never FAIL. In `proof verify`
  and `proof check` the timeout is `[verify].command_timeout` (default 600
  seconds), for the claim's checks and the red-green repro runs alike. In the
  Stop hook it is the smaller of that and the remaining `[verify].inline_budget`.

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
above.

**Verdict rules:**
- PASS -- command exits 0
- FAIL -- command exits non-zero (any value other than 0 or 127)
- INCONCLUSIVE -- no test runner detected (confidence 0.3) OR command not found
  (exit code 127, e.g. `pytest` not installed)
- DEFERRED -- the command timed out

---

## build

**Detection:** triggered when the claim contains phrases like "build is clean",
"build is green", "build is passing", or "builds success".

**Execution:** calls `detect_build_cmd(root)` to auto-detect the build command.
Detection order: `package.json` with a `build` script (runs `npm run build`),
`Cargo.toml` (runs `cargo build -q`), `go.mod` (runs `go build ./...`). A
`command` argument overrides auto-detection.

**Verdict rules:**
- PASS -- command exits 0
- FAIL -- command exits non-zero (any value other than 0 or 127)
- INCONCLUSIVE -- no build command detected OR command not found (exit 127);
  confidence 0.3

---

## typecheck

**Detection:** triggered when the claim mentions "typecheck" or "type-check".

**Execution:** no auto-detection; requires `[commands].typecheck` (e.g.
`tsc --noEmit`).

**Verdict rules:**
- PASS -- command exits 0
- FAIL -- command exits non-zero (any value other than 0 or 127)
- INCONCLUSIVE -- no command supplied OR command not found (exit 127); confidence 0.3

---

## lint

**Detection:** triggered when the claim contains "linting passes" or "lint clean".

**Execution:** no auto-detection; requires `[commands].lint` (e.g.
`eslint .` or `ruff check .`).

**Verdict rules:**
- PASS -- command exits 0
- FAIL -- command exits non-zero (any value other than 0 or 127)
- INCONCLUSIVE -- no command supplied OR command not found (exit 127); confidence 0.3

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

## Library strategies: command, repro, filecheck

These three strategies are still registered and callable through the Python
API, but claim text no longer routes to them. In v3, "I fixed the bug" is
proven by the `redgreen` analyzer and "I added X to Y" is checked by the
`scope` analyzer, both below.

- `command` and `repro` run the given command with the shared verdict rules
  above. Without a command they are INCONCLUSIVE (confidence 0.2).
- `filecheck` reads the file named by `expectation` and searches it for the
  `command` string. PASS when found, FAIL when absent, INCONCLUSIVE when the
  file does not exist (confidence 0.3).

---

# Diff analyzers

The analyzers compare the current working tree against a baseline commit, the
first of:

- the ref given with `--since` (for example `origin/main` in CI),
- the session baseline captured at SessionStart (`refs/proof/baseline/<session>`),
- `HEAD`, when neither exists. That baseline is approximate, and the report
  says "baseline: HEAD (approximate)". Scope and red-green are skipped on an
  approximate baseline; tamper still runs.

Outside a git repository all three are skipped with a note. When the project
root is a subdirectory of the repository, the diff is limited to that
subdirectory. Proof's own artifacts (`proof-report.md`, `.proof/`,
`__pycache__/`, `*.pyc`) never appear in the diff.

An exception inside an analyzer skips that analyzer with a note in the report.
It never produces FAIL or SUSPECT.

---

## tamper

**Runs when:** the claim includes a `tests` or `build` check and
`[tamper].enabled` is not `false`.

**Verdict:** SUSPECT with one finding per hit, or no result when nothing is
found. Headline: `possible test tampering: <counts per rule>`.

**Test files** are recognized by path: anything under `test/`, `tests/`,
`__tests__/`, `spec/`, or `specs/`, plus `test_*.py`, `*_test.py`,
`conftest.py`, `*.test.[cm]?[jt]sx?`, `*.spec.[cm]?[jt]sx?`, and `*_test.go`.
Rust source files outside those directories also count for the skip and
test-removal rules, since Rust tests live inline.

**Rules.** Each rule can be turned off with `[tamper] disable = ["<rule id>"]`.
Comment lines never count. Rules marked *pooled* are netted across the whole
change: a skip removed in one file offsets a skip added in another, so moving or
renaming tests is silent.

| Rule id | Detects | Scope and exceptions |
|---|---|---|
| `test-file-deleted` | A test file present in the baseline is deleted | Silent when the file was moved or renamed (the same file name is added elsewhere, or its test definitions reappear in another test file), or when the source file it covers is deleted too. |
| `test-removed` | Net removal of test definitions: `def test_`, `async def test_`, `it(`, `test(`, `func Test`, `#[test]`, `#[tokio::test]` | Pooled. Test files and Rust sources. Silent when the tested name also disappears from non-test code (the feature itself was removed). |
| `skip-added` | Added `@pytest.mark.skip`, `@pytest.mark.xfail`, `pytest.skip(`, `pytest.xfail(`, `@unittest.skip`, `@unittest.expectedFailure`, `self.skipTest(`, `it.skip`, `describe.skip`, `test.skip`, `context.skip`, `xit(`, `xdescribe(`, `xtest(`, `this.skip(`, `test.fixme(`, `t.Skip(`, `t.Skipf(`, `t.SkipNow(`, `#[ignore]` | Pooled. Test files and Rust sources. Not flagged: conditional skips (`skipif`, `skipUnless`, `importorskip`), `todo`, `pytest.skip(` inside `conftest.py`, and a Go `t.Skip` guarded by `testing.Short()`. |
| `only-added` | Added `.only(` on `it`, `describe`, `test`, or `context`, which silently disables every other test; `fit(` and `fdescribe(` in JS/TS files | Pooled. Test files. |
| `assert-gutted` | Net removal of assertion lines, or added trivial assertions: `assert True`, `assert 1`, `expect(true).toBe(true)`, `assert.ok(true)`, `self.assertTrue(True)`, `assert!(true)` | Pooled. Test files by path, so Rust asserts count only under `tests/`. Files that also lost test definitions are left to `test-removed`. |
| `runner-neutered` | The test command changed so it cannot fail | Added lines only. The `package.json` `test` script turned into a no-op (`exit 0`, `true`, `:`, a bare `echo`) or given `--passWithNoTests`, or a `test` or `test:*` script whose runner is followed by `\|\| true` or `exit 0`. Runner lines in `Makefile` and `*.mk` test targets with `\|\| true`, `exit 0`, or `--passWithNoTests`. Pytest config (`addopts`, or a `[pytest]`, `[tool:pytest]`, or `[tool.pytest.ini_options]` section in `pytest.ini`, `setup.cfg`, `tox.ini`, or `pyproject.toml`) adding `-k`, `--deselect`, or `--ignore` of a test path. `tox.ini` testenv runner lines with `\|\| true` or `exit 0`. Runner lines in `.github/workflows/*.yml` with `\|\| true`, `exit 0`, or `--passWithNoTests`. A `.proof.toml` `test` key set to a no-op or ending in `\|\| true`. |

---

## scope

**Runs when:** the claim is a change claim ("I fixed", "the bug is fixed",
"I added", "I implemented", "I created", "I wrote", "I introduced", "is now
implemented", "feature is complete") and the baseline is not approximate.
Pure verification claims ("tests pass") with no changes are fine.

**Verdict:** SUSPECT, headline `claim does not match the diff: <rule ids>`.

Changes to `.proof.toml`, `proof-report.md`, and `.proof/` are ignored here.
Named items are backticked tokens in a sentence that contains `added`,
`created`, `implemented`, `wrote`, or `introduced`. A token counts as a path
when it has a known source or config extension, starts with `./` or `../`, ends
with `/`, or matches a changed file name. It counts as a symbol when it is a
plain identifier (`parse_price`, `Cart.total`, `render()`). URLs, absolute
paths, and version numbers are ignored.

| Rule id | Fires when |
|---|---|
| `empty-change` | Nothing changed since the baseline, and the claim says "I fixed" or names a path or symbol. |
| `docs-only` | The claim is a fix or names code, and every changed file is documentation (`.md`, `.rst`, `.adoc`, `docs/`, `README`, `CHANGELOG`, `LICENSE`), or every changed line in code files is a comment. Extensionless files (`Makefile`, `Dockerfile`, dotfiles) and binary or mode-only changes count as real changes. |
| `named-path-unchanged` | A named path is not in the change. |
| `named-symbol-missing` | A named symbol appears nowhere in the change: not in a changed line, not as a changed file name, and not in the current contents of any changed file. |

---

## redgreen

**Runs when:** the claim is a fix claim ("I fixed", "I've fixed", "the bug is
fixed", "it is now fixed", "now fixed") and the baseline is not approximate.

**Repro source, first match wins:**

1. Test files added or modified since the baseline, targeted per runner:
   pytest (`<test cmd> <paths>`), go (`go test <package dirs>`), and JS runners
   (`npm test -- <paths>`, or `<cmd> <paths>` for pnpm, yarn, bun, jest, and
   vitest). The base command comes from `[commands].test` or auto-detection.
   Other runners skip this source.
2. `[repro].command` in `.proof.toml`.
3. A ``Repro: `<command>` `` line in the claim message.

With no source, there is no redgreen result. The report gets a note, and a hook
block reason ends with a hint asking for a changed test or a `Repro:` line.

**Run:**

1. `git worktree add --detach` of the baseline commit into a fresh temporary
   directory under `$PROOF_HOME/work`, with git hooks disabled.
2. Copy the changed test files from the current tree into the worktree, so the
   new test runs against the old code.
3. Link `node_modules` into the worktree when the project has one (a junction on
   Windows, a symlink elsewhere). For Python, prepend the tree (and its `src/`)
   to `PYTHONPATH`.
4. Run the repro in the worktree (red), then in the current tree (green), both
   from the project directory.
5. Remove the dependency link first, then the worktree, always. If the link
   cannot be removed, the worktree is left in place with a note rather than
   risk deleting through the link into the real `node_modules`. Only this
   worktree's own registration is removed.

**Verdict:**

| Baseline | Current | Verdict |
|---|---|---|
| fails cleanly | passes | PASS: "fix proven: repro failed before the change and passes now" |
| passes | passes | SUSPECT (`repro-already-green`): the repro passes without your change, so it does not prove the fix |
| any | fails | FAIL |
| could not run cleanly | passes | INCONCLUSIVE |
| timed out, or under 10 s of budget left | | deferred |

"Fails cleanly" means the failure is evidence that a test ran and failed, not
that the environment broke. It depends on the runner:

| Runner | Counts as a clean red | Counts as "could not run" |
|---|---|---|
| any | non-zero exit | exit 127, "command not found", "No module named", "Cannot find module", `ENOENT`, "no tests ran", "collected 0 items" |
| pytest | exit 1 only | any other exit (2 collection or interrupt error, 4 usage error, 5 no tests) |
| jest, vitest, npm/yarn/pnpm/bun test | non-zero exit | "Test suite failed to run", "Failed to load", "Failed to resolve import", `SyntaxError` |
| go test | a `--- FAIL` line | `[build failed]`, `[setup failed]`, `undefined:`, or no `--- FAIL` line |

The runner is decided by the repro command itself, whatever its source.
