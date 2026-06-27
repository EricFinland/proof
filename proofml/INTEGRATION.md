# proofml shadow mode: integration spec

This is the contract for proofml's shadow mode. Parallel build agents code
against THIS file. Shadow mode is an additive, opt-in layer over the shipping
`proof` tool. When it is OFF (the default), `proof` behaves exactly as before:
identical ledger keys, identical verdict, identical exit code, identical output.

## 1. The shadow predictor contract: `proofml.shadow.predict`

```python
predict(
    claim: str,
    transcript_path: str | None = None,
    root: str | None = None,
    model_path: str | None = None,
) -> dict | None
```

Behavior:

- Model resolution precedence: `model_path` arg > env `PROOFML_MODEL` >
  `proofml/artifacts/model.joblib` (resolved relative to the proofml package
  directory). If no model file exists, return `None`.
- Behavioral signals:
  - If `transcript_path` is given and readable, the raw signals
    (`ran_test_cmd`, `claimed_without_running`, `diff_lines`,
    `touched_test_files`, `hedged`, `absolute`) and the effective claim come
    from `proofml.extract.extract_features` (the last assistant text is the
    claim). `source = "transcript"`.
  - Otherwise the claim text is used directly: behavioral fields default
    (0 / False), `hedged` / `absolute` are derived from the claim text.
    `source = "claim_only"`.
- Featurization goes through `proofml.features.to_matrix` (the ONE shared path),
  so the dataset builder re-featurizes raw signals with zero drift.
- `joblib` and `scikit-learn` are imported lazily INSIDE the function.
- `predict()` NEVER raises. On any failure (missing deps, missing model,
  unreadable transcript, malformed model) it returns `None`.

Return value (EXACT shape, or `None`):

```python
{
  "proba": float,        # P(deceptive) for this claim, 0..1
  "model": str,          # chosen_model from metrics.json if available, else model file stem
  "source": "transcript" | "claim_only",
  "behavior": {          # RAW signals, NOT the featurized vector
    "ran_test_cmd": bool,
    "claimed_without_running": bool,
    "diff_lines": int,
    "touched_test_files": bool,
    "hedged": bool,
    "absolute": bool
  }
}
```

## 2. The proof-side bridge: `proofkit.shadow`

`proof/scripts/proofkit/shadow.py` is the only place `proof` touches `proofml`.
It imports stdlib only at module import time so `proofkit` stays
zero-dependency.

```python
maybe_predict(claim: str, transcript: str = "", root: str = ".") -> dict | None
```

- Checks the trigger first (see section 3). If not enabled, returns `None`
  immediately and does NOT import `proofml` at all.
- If enabled: `import proofml.shadow`. On `ImportError`, if env `PROOFML_PATH`
  is set, `sys.path.insert(0, PROOFML_PATH)` and retry; still failing returns
  `None`.
- Calls `proofml.shadow.predict(claim, transcript_path=transcript or None,
  root=root)` and returns its dict or `None`.
- Everything is wrapped in try/except; it never raises.

## 3. The trigger: when shadow runs

Shadow prediction + logging happens IFF EITHER:

- env var `PROOFML_SHADOW` is truthy: one of `"1"`, `"true"`, `"yes"`
  (case-insensitive, surrounding whitespace ignored), OR
- `.proof.toml` has a `[shadow]` table with `enabled = true`.

If neither, the code path is a NO-OP and the ledger entry is identical to today.
Default = OFF.

`.proof.toml` example:

```toml
[shadow]
enabled = true
```

Optional related env vars:

- `PROOFML_MODEL`: override the model file path.
- `PROOFML_PATH`: directory to add to `sys.path` so `import proofml` resolves
  in a prod install where proofml is not already importable.

## 4. The enriched ledger entry (the live labeled dataset)

`proof/scripts/proofkit/verdict.py` `_execute_claims` builds the ledger entry,
then (guarded, before `append_entry`) calls `maybe_predict` for the primary
claim. When shadow returns a dict, these ADDITIVE keys are added:

| key            | type  | meaning                                  |
| -------------- | ----- | ---------------------------------------- |
| `shadow_proba` | float | P(deceptive) predicted before verifying  |
| `shadow_model` | str   | model name used                          |
| `shadow_source`| str   | `"transcript"` or `"claim_only"`         |
| `behavior`     | dict  | the 6 raw signals (see section 1)        |

Existing keys are unchanged and always present:
`project`, `overall`, `n_claims`, `fails`, `claims`, `ts`.

When shadow is OFF, `maybe_predict` returns `None` and the entry has ONLY the
existing keys (byte-for-byte identical to pre-shadow behavior). Existing ledger
consumers (`compute_stats`) read only `overall` / `fails` / `claims` / `ts` and
keep working regardless.

`run_verify` passes `transcript=transcript` to `_execute_claims`; `run_check`
passes `transcript=""` (claim-only mode). No other signature, return value, or
printed-output behavior changes.

## 5. The dataset row format: `proofml.dataset`

```
python -m proofml.dataset build  --ledger <ledger.jsonl> --out data/real.jsonl [--include-thin]
python -m proofml.dataset report --ledger <ledger.jsonl>
```

`build`: reads the enriched ledger and emits one `Example` per claim string for
entries with `overall` in `{pass, fail}` (`inconclusive` dropped).

- `label = 1` if `overall == "fail"`, else `0`.
- If the entry has a `behavior` dict, the raw fields are copied in and
  `source = "transcript"` (a FEATURED row).
- Otherwise the behavioral fields stay at neutral defaults and
  `source = "ledger"` (a THIN row). Thin rows are emitted only with
  `--include-thin`.
- Output is the standard `examples.jsonl` interchange (`asdict(Example)` per
  line) via `proofml.data.write_examples`. Prints featured-vs-thin counts and
  label balance.

`report`: over entries that have BOTH `shadow_proba` AND `overall` in
`{pass, fail}`, treats `y_true = label`, `y_score = shadow_proba`, and prints
live PR-AUC, Brier, accuracy@0.5, and a bucketed calibration table (mean
predicted vs observed deceptive rate). This answers "how well did past shadow
predictions match the real verdict." If scikit-learn is missing, accuracy and
Brier are computed without it and PR-AUC is skipped with a note. With fewer than
2 usable rows or a single verdict class, it prints a clear "not enough data"
message and exits 0.

## 6. Hard invariants

- `proofkit` stays stdlib-only at import time. `joblib` / `scikit-learn` are
  imported lazily inside `proofml` only, never inside `proofkit`.
- Shadow logic never changes proof's verdict, exit code, printed output, or
  existing ledger keys when OFF.
- The existing proofml model and artifacts are never retrained or modified by
  this layer.
