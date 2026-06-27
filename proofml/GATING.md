# proofml cost-gated verification: the gate contract

This is the contract for proofml's cost gate. Parallel build agents code against
THIS file. The gate is an additive, opt-in layer over the shipping `proof` tool
and its Stop hook. When it is OFF (the default), `proof` behaves exactly as
before: identical block decisions, identical output, identical exit codes, and
the full existing proof test suite stays green.

## 0. What gating does

Today proof's Stop hook (`proof_trigger.py`) BLOCKS when an agent claims work is
complete, forcing an expensive independent verifier subagent. The gate lets
proofml SKIP that verification when it is confident the claim is honest, applying
the cascade's calibrated operating point live. It is the cascade's threshold,
applied at the moment of the claim.

The gate can only ever SUPPRESS the verifier. It never changes the verify path
itself, the ledger schema for real verdicts, or any non-gated behavior.

## 1. Safety invariants (non-negotiable)

1. **OPT-IN.** Gating runs IFF env `PROOFML_GATE` is truthy (`"1"`, `"true"`,
   `"yes"`, case-insensitive, surrounding whitespace ignored) OR `.proof.toml`
   `[gate]` `enabled = true`. Default OFF. When OFF, `decide()` returns `None`
   immediately, proofml is never imported, nothing is logged, and the hook
   blocks exactly as today.
2. **FAIL-SAFE.** Any uncertainty => VERIFY. If the predictor errors, the model
   is missing, `proba` is `None`/unparseable, proofml can't import, or anything
   is wrong, the gate falls through to normal blocking. It NEVER skips on error.
   `decide()` NEVER raises.
3. **SKIP ONLY THE FIRST CHECK.** The gate may only skip a claim's FIRST
   verification. The hook reaches the gate only when `should_block(...)` already
   returned `True`; it additionally requires `last_outcome(session, claim)` to be
   `None` before considering a skip. A re-verification after a prior
   fail/inconclusive is never skipped.
4. **ADDITIVE.** Gating never changes proof's verdict, exit code, the real-verdict
   ledger keys, or any non-gated behavior.

## 2. The gate decision: `proofkit.gate.decide`

```python
decide(claim, transcript="", root=".", session="", marker_root=None) -> dict | None
```

- If gating is not enabled (the trigger check in section 4) -> return `None`. The
  caller proceeds to block as normal and NOTHING is logged. proofml is NOT
  imported on this path.
- Otherwise, get a prediction via `proofkit.shadow.predict_now(claim,
  transcript, root)` (section 3) -> a dict `{proba, model, source, behavior}` or
  `None`.
- If the prediction is `None` (or `proba` is `None`/unparseable) -> FAIL-SAFE:
  log `decision="verify"` with a `reason` and return `{"decision": "verify"}`.
- Resolve the threshold and audit rate (section 5).
- If `proba >= threshold` -> `decision="verify"` (predicted risky; block).
- Else (`proba < threshold`, predicted honest):
  - `roll = random.random()`; if `roll < audit_rate` -> `decision="audit"`
    (still verify, but a sampled audit); else `decision="skip"` (trust the claim,
    skip the verifier).
- ALWAYS append a `gate.jsonl` decision line for every non-`None` path
  (verify/audit/skip), then return `{"decision": ...}`.

Return values:

| return                  | caller behavior                                  |
| ----------------------- | ------------------------------------------------ |
| `None`                  | gating disabled; block as normal, nothing logged |
| `{"decision": "skip"}`  | trust the claim; SKIP the verifier               |
| `{"decision": "verify"}`| block normally (risky, or fail-safe)             |
| `{"decision": "audit"}` | still block, but as a sampled audit              |

Only `"skip"` suppresses the verifier. `"verify"` and `"audit"` both block.

## 3. Predictor split: `proofkit.shadow`

`proofkit/shadow.py` keeps `maybe_predict` byte-identical (trigger check THEN
predict) and adds:

```python
predict_now(claim, transcript="", root=".") -> dict | None
```

`predict_now` is the lower half of `maybe_predict` with NO trigger check: it
lazily imports `proofml.shadow` (with the `PROOFML_PATH` fallback) and calls
`predict`, guarded, never raising. The gate calls `predict_now` AFTER its own
`[gate]` trigger, so gating works regardless of the `PROOFML_SHADOW` setting.
`maybe_predict` is now `if is_enabled(root): return predict_now(...) else None`,
so existing shadow tests stay green.

## 4. The trigger: when the gate runs

Gating runs IFF EITHER:

- env `PROOFML_GATE` is truthy (`"1"` / `"true"` / `"yes"`, case-insensitive), OR
- `.proof.toml` has a `[gate]` table with `enabled = true`.

If neither, `decide()` is a no-op returning `None`. Default = OFF.

`.proof.toml` example:

```toml
[gate]
enabled = true
threshold = 0.1
audit_rate = 0.1
```

## 5. Threshold and audit-rate resolution

**Threshold** (probability-of-deception cutoff; `proba >= threshold` => verify):

1. env `PROOFML_GATE_THRESHOLD`
2. `.proof.toml` `[gate].threshold`
3. `artifacts/operating_point.json` `["threshold"]` (the calibrated value from
   the cascade). Located via the directory of env `PROOFML_MODEL` if set, else a
   sibling `proofml/artifacts/operating_point.json` (also honoring
   `PROOFML_PATH`). Resolved with stdlib only; proofml is NOT imported.
4. default `0.1`

**Audit rate** (fraction of predicted-honest claims still verified as a sampled
audit), clamped to `[0, 1]`:

1. env `PROOFML_GATE_AUDIT_RATE`
2. `.proof.toml` `[gate].audit_rate`
3. default `0.1`

Related env vars (shared with shadow mode): `PROOFML_MODEL` (model file path
override), `PROOFML_PATH` (dir added to `sys.path` so `import proofml` resolves).

## 6. `gate.jsonl` decision log

Lives in the marker root: env `PROOF_HOME` if set, else `~/.proof`. One JSON
object per line, appended for every non-`None` `decide()` path. Logging never
raises; a logging failure is swallowed.

```json
{
  "ts": 1700000000.0,
  "project": "myrepo",
  "session": "s1",
  "claim": "All done, tests pass.",
  "proba": 0.04,
  "threshold": 0.1,
  "audit_rate": 0.1,
  "decision": "skip",
  "source": "transcript",
  "behavior": {
    "ran_test_cmd": true,
    "claimed_without_running": false,
    "diff_lines": 12,
    "touched_test_files": true,
    "hedged": false,
    "absolute": true
  }
}
```

| key          | type                                   | notes                                  |
| ------------ | -------------------------------------- | -------------------------------------- |
| `ts`         | float                                  | epoch seconds, stamped if absent       |
| `project`    | str                                    | basename of `root`                     |
| `session`    | str                                    | proof session id                       |
| `claim`      | str (<= 120 chars)                     | truncated claim text                   |
| `proba`      | float or null                          | P(deceptive); null on predict failure  |
| `threshold`  | float                                  | resolved threshold                     |
| `audit_rate` | float                                  | resolved, clamped audit rate           |
| `decision`   | `"skip"` / `"verify"` / `"audit"`      | the gate decision                      |
| `source`     | `"transcript"` / `"claim_only"` / null | prediction source                      |
| `behavior`   | dict (6 raw signals) or null           | raw signals from the prediction        |
| `reason`     | str (optional)                         | e.g. `predict_failed`, `proba_none`, `gate_error` |

## 7. `operating_point.json` schema

Written additively by `proofml.cascade.run_cascade` into `artifacts/`. This is
the calibrated threshold the gate reads. The cascade's existing outputs
(`cascade.png` / `cascade_frontier.csv`) and metrics are unchanged.

```json
{
  "threshold": 0.42,
  "min_recall": 0.95,
  "recall": 0.97,
  "skip_rate": 0.61,
  "model": "logistic_regression",
  "n_held": 120,
  "n_lies": 30
}
```

None-safe: when no operating point meets `min_recall`, the cascade writes
`threshold: null` (and `recall`/`skip_rate`/`n_lies` null) and prints a note. The
gate treats a missing/null threshold as "not available" and falls back to the
next resolution source / default, so it never skips on a null threshold.

| key          | type          | meaning                                            |
| ------------ | ------------- | -------------------------------------------------- |
| `threshold`  | float or null | chosen `proba` cutoff; null if unreachable recall  |
| `min_recall` | float         | the recall floor used to pick the point            |
| `recall`     | float or null | recall on deception at the chosen threshold        |
| `skip_rate`  | float or null | fraction of verifier runs skipped at that point    |
| `model`      | str           | `chosen_model` from metrics.json, else `"model"`   |
| `n_held`     | int           | held-out rows the frontier was computed on         |
| `n_lies`     | int or null   | deceptive rows in the held-out set                 |

## 8. Hook wiring (`proof_trigger.py`)

After `if not should_block(...): return` (proof intends to verify) and BEFORE
`record_attempt`, a guarded gate check runs:

```python
try:
    prior = last_outcome(session, msg, root=marker_root)
    if prior is None:
        from proofkit.gate import decide
        g = decide(msg, transcript=tp, root=str(cwd_path),
                   session=session, marker_root=marker_root)
        if g and g.get("decision") == "skip":
            return  # trust the claim; skip the verifier (logged in gate.jsonl)
except Exception:
    pass  # fail-safe: fall through to normal blocking
```

Everything else (record_attempt, the block directive, receipts) is unchanged.
When the gate is OFF, `decide` returns `None`, the `if` is skipped, and the hook
records the attempt and blocks exactly as today.

## 9. Safety report: `proofml.dataset gate`

```
python -m proofml.dataset gate --gate <gate.jsonl> [--ledger <ledger.jsonl>]
```

Reports: total decisions; counts of skip/verify/audit; SKIP RATE =
`skip / (skip + verify + audit)` (the fraction of verifier runs saved); mean
`proba` by decision.

SAFETY: with `--ledger`, joins audited decisions to their real verdict by
`project` + claim text (prefix match, since the gate truncates the claim) +
nearest `ts` within a window. On the audited slice (claims predicted honest but
verified anyway), it reports how many turned out FAIL = gate MISSES (false
negatives) and the audit-slice MISS RATE. That miss rate is the number that says
whether the gate is safe to keep. Empty/missing files are handled gracefully with
a clear message and exit 0.

## 10. Hard invariants

- `proofkit` stays stdlib-only at import time. proofml / sklearn / joblib are
  imported lazily inside proofml only, never inside proofkit.
- Gate OFF => `proof_trigger` behaves byte-identically; the full existing proof
  suite stays green.
- Fail-safe always: on any error, VERIFY (block). A bug must never cause a skip.
- The existing proofml model and artifacts are never retrained or modified by
  this layer.
