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

`proof.py verify` exits with:

| Exit code | Verdict |
|---|---|
| 0 | PASS |
| 1 | FAIL |
| 2 | INCONCLUSIVE |

This mapping makes `proof.py verify` usable as a CI gate: a non-zero exit
indicates that verification did not pass.
