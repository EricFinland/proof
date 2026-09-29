# Evidence Format

## proof-report.md layout

`proof-report.md` is written by `scripts/proofkit/verdict.py:write_report()` to
the `--out-dir` of the `proof.py verify` invocation (the current directory by
default; the Stop hook writes it to the project root). It uses Markdown so it
renders in GitHub and most editors.

### Structure

```
# Proof Report -- <OVERALL_VERDICT>

## <PER_RESULT_VERDICT> -- <method>
- **Claim:** <first 200 chars of the claim text>
- **Command:** `<command that was run>`

```
<raw command output, up to 3000 chars>
```

## <PER_RESULT_VERDICT> -- <method>
...

## Notes

- <note>
```

The overall verdict appears in the H1 heading. Each result gets an H2 section
with the verdict, method name, the original claim text, the command that was
executed, and the captured stdout + stderr (truncated to 3000 characters).

`<method>` is a strategy name (`tests`, `build`, `typecheck`, `lint`, `http`)
or a diff analyzer (`tamper`, `scope`, `redgreen`). Analyzer sections show
`git diff (baseline)` as the command for `tamper` and `scope`, and the repro
command for `redgreen`.

### Example: FAIL

```
# Proof Report -- FAIL

## FAIL -- tests
- **Claim:** All done, tests pass.
- **Command:** `python -m pytest -q`

```
FAILED tests/test_bad.py::test_bad - AssertionError: assert 1 == 2
1 failed in 0.05s
```
```

### SUSPECT sections

A SUSPECT section's body is a one-line headline followed by one line per
finding:

```
<headline>
<rule>: <file>:<line>  <snippet>
<rule>: <file>:<line>  <snippet>
```

The location is omitted when a finding has no file, and `:<line>` is omitted
when it has no line number (a deleted file, for instance). Snippets are cut to
160 characters. Headlines by analyzer:

| Analyzer | Headline |
|---|---|
| `tamper` | `possible test tampering: 2 skips added and 1 test file deleted` (counts per rule) |
| `scope` | `claim does not match the diff: docs-only, named-path-unchanged` (rule ids) |
| `redgreen` | `fix not proven` |

Example:

```
# Proof Report -- SUSPECT

## PASS -- tests
- **Claim:** All done, tests pass.
- **Command:** `python -m pytest -q`

```
.s                                                                       [100%]
1 passed, 1 skipped in 0.01s
```

## SUSPECT -- tamper
- **Claim:** All done, tests pass.
- **Command:** `git diff (baseline)`

```
possible test tampering: 1 skip added
skip-added: tests/test_pricing.py:10  @pytest.mark.skip(reason="flaky on CI")
```
```

### Notes section

When the analyzers have something to say that is not a verdict, the report ends
with a `## Notes` list. Notes never change the verdict. Possible notes:

- `no git baseline: tamper, scope, and redgreen checks skipped` (not a git repo)
- `baseline: HEAD (approximate)` (no session baseline was captured)
- `<analyzer> analysis skipped: <error>` (an analyzer raised; it is skipped,
  never turned into FAIL or SUSPECT)
- `no repro found for this fix claim; add or change a test, or include a line
  Repro: `<command>` that failed before the fix`

---

## Verdict vocabulary

There are four verdicts, used identically in Result objects, the aggregate, the
printed stdout line, and the report heading:

| Verdict | Meaning |
|---|---|
| `pass` / `PASS` | Every check that ran passed, and no analyzer found gaming. |
| `fail` / `FAIL` | At least one check produced evidence of failure. |
| `suspect` / `SUSPECT` | The checks pass, but the diff shows they were gamed, a fix was never red, or the claim contradicts the diff. |
| `inconclusive` / `INCONCLUSIVE` | No check produced a definitive result (no runner detected, command not found, no URL, timed out, etc.). |

A fifth value, `deferred`, is internal. It marks a check that did not finish
inside the time budget. It counts as INCONCLUSIVE in the aggregate, and the
Stop hook hands deferred checks to a verifier subagent.

The report and stdout use uppercase. The internal `Result.verdict` field and the
aggregation logic use lowercase.

---

## Aggregation

The `aggregate()` function in `scripts/proofkit/verdict.py` ranks verdicts by
severity: `fail > suspect > pass > inconclusive`.

1. If any result is `fail`, the overall verdict is `fail`.
2. Otherwise, if any result is `suspect`, the overall verdict is `suspect`.
3. Otherwise, if any result is `pass`, the overall verdict is `pass`.
4. Otherwise (all results inconclusive or deferred, or no results), the overall
   verdict is `inconclusive`.

A single FAIL from any strategy overrides everything else. A SUSPECT overrides
passing checks, so gamed tests can never produce a clean PASS. An empty result
list (no claims extracted) is INCONCLUSIVE.

---

## Exit-code mapping

`proof.py verify` and `proof.py check` exit with:

| Exit code | Verdict |
|---|---|
| 0 | PASS |
| 1 | FAIL |
| 2 | INCONCLUSIVE |
| 3 | SUSPECT |

This mapping makes `proof.py verify` and `proof.py check` usable as CI gates:
any non-zero exit means verification did not pass. Exit code 3 lets a pipeline
treat gaming differently from a plain failure if it wants to.

---

## JSON output (--json)

Both `verify` and `check` accept `--json`. When set, a single JSON object is
printed to stdout instead of the ASCII verdict lines. The process exit code is
unchanged.

### Schema

```json
{
  "overall": "pass" | "fail" | "suspect" | "inconclusive",
  "exit":    0 | 1 | 2 | 3,
  "results": [
    {
      "claim":      "<original claim text>",
      "method":     "<strategy or analyzer name>",
      "command":    "<command that was run>",
      "raw_output": "<captured stdout+stderr, up to 2000 chars>",
      "verdict":    "pass" | "fail" | "suspect" | "inconclusive" | "deferred",
      "confidence": <float 0.0-1.0>,
      "findings":   [
        {"rule": "<rule id>", "file": "<path>", "line": <int>, "snippet": "<text>"}
      ]
    }
  ],
  "report":  "<out-dir>/proof-report.md"
}
```

### Key notes

- `overall` mirrors the exit code: `"pass"` -> 0, `"fail"` -> 1,
  `"inconclusive"` -> 2, `"suspect"` -> 3.
- `results` has one entry per extracted claim plus one per analyzer that
  produced a verdict.
- `findings` is always present. It is empty except on SUSPECT results from
  `tamper`, `scope`, and `redgreen`. `file` is a path relative to the git
  toplevel (empty when the finding is about the whole change), and `line` is
  the line number in the current file, or `0` when there is none.
- `raw_output` is truncated to 2000 characters per result.
- `report` is a non-empty string path on every run that produced results; it
  is an empty string when `check` found nothing to verify.
- When `check` is given text with no recognizable claims and the analyzers find
  nothing, the output is
  `{"overall": "inconclusive", "exit": 2, "results": [], "report": ""}`.

### Example

```bash
$ proof check "all tests pass" --root /my/project --since origin/main --json
{
  "overall": "suspect",
  "exit": 3,
  "results": [
    {
      "claim": "all tests pass",
      "method": "tests",
      "command": "python -m pytest -q",
      "raw_output": ".s    [100%]\n1 passed, 1 skipped in 0.01s",
      "verdict": "pass",
      "confidence": 1.0,
      "findings": []
    },
    {
      "claim": "all tests pass",
      "method": "tamper",
      "command": "git diff (baseline)",
      "raw_output": "possible test tampering: 1 skip added\nskip-added: tests/test_pricing.py:10  @pytest.mark.skip(reason=\"flaky on CI\")",
      "verdict": "suspect",
      "confidence": 0.9,
      "findings": [
        {"rule": "skip-added", "file": "tests/test_pricing.py", "line": 10,
         "snippet": "@pytest.mark.skip(reason=\"flaky on CI\")"}
      ]
    }
  ],
  "report": "proof-report.md"
}
```
