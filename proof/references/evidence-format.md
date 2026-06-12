# Evidence Format

## proof-report.md layout

`proof-report.md` is written by `scripts/proofkit/verdict.py:write_report()` to
the working directory of the `proof.py verify` invocation. It uses Markdown so
it renders in GitHub and most editors.

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
```

The overall verdict appears in the H1 heading. Each result gets an H2 section
with the verdict, method name, the original claim text, the command that was
executed, and the captured stdout + stderr (truncated to 3000 characters).

### Example

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

---

## Verdict vocabulary

There are exactly three verdicts, used identically in Result objects, the
aggregate, the printed stdout line, and the report heading:

| Verdict | Meaning |
|---|---|
| `pass` / `PASS` | Every strategy check exited 0 (or HTTP status matched). Work is confirmed. |
| `fail` / `FAIL` | At least one strategy check produced evidence of failure. |
| `inconclusive` / `INCONCLUSIVE` | No check produced a definitive result (no runner detected, command not found, no URL, etc.). |

The report and stdout use uppercase (`PASS`, `FAIL`, `INCONCLUSIVE`). The
internal `Result.verdict` field and the aggregation logic use lowercase
(`pass`, `fail`, `inconclusive`).

---

## Strict "any fail -> FAIL" rule

The `aggregate()` function in `scripts/proofkit/verdict.py` applies these
rules in order:

1. If any result has `verdict == "fail"`, the overall verdict is `"fail"`.
2. Otherwise, if any result has `verdict == "pass"`, the overall verdict is
   `"pass"`.
3. Otherwise (all results are inconclusive, or there are no results), the
   overall verdict is `"inconclusive"`.

A single FAIL from any strategy overrides all passing strategies.
An empty result list (no claims extracted) is INCONCLUSIVE.

---

## Exit-code mapping

`proof.py verify` and `proof.py check` exit with:

| Exit code | Verdict |
|---|---|
| 0 | PASS |
| 1 | FAIL |
| 2 | INCONCLUSIVE |

This mapping makes `proof.py verify` and `proof.py check` usable as CI gates:
a non-zero exit indicates that verification did not pass.

---

## JSON output (--json)

Both `verify` and `check` accept `--json`. When set, a single JSON object is
printed to stdout instead of the ASCII verdict lines. The process exit code is
unchanged.

### Schema

```json
{
  "overall": "pass" | "fail" | "inconclusive",
  "exit":    0 | 1 | 2,
  "results": [
    {
      "claim":      "<original claim text>",
      "method":     "<strategy name>",
      "command":    "<command that was run>",
      "raw_output": "<captured stdout+stderr, up to 2000 chars>",
      "verdict":    "pass" | "fail" | "inconclusive",
      "confidence": <float 0.0-1.0>
    }
  ],
  "report":  "<absolute path to proof-report.md>"
}
```

### Key notes

- `overall` mirrors the exit code: `"pass"` -> 0, `"fail"` -> 1,
  `"inconclusive"` -> 2.
- `results` is a list with one entry per claim extracted from the message.
- `raw_output` is truncated to 2000 characters per result.
- `report` is a non-empty string path on every successful run; it may be an
  empty string if no claims were found (`check` with unmappable text).
- When `check` is given text with no recognizable claims, the output is
  `{"overall": "inconclusive", "exit": 2, "results": [], "report": ""}`.

### Example

```bash
$ proof check "all tests pass" --root /my/project --json
{
  "overall": "fail",
  "exit": 1,
  "results": [
    {
      "claim": "all tests pass",
      "method": "tests",
      "command": "python -m pytest -q",
      "raw_output": "FAILED tests/test_foo.py::test_bar\n1 failed in 0.12s",
      "verdict": "fail",
      "confidence": 1.0
    }
  ],
  "report": "/my/project/proof-report.md"
}
```
