# Shadow Mode

Shadow mode lets proof log a deception prediction next to every real verdict
without changing anything proof does. It is the first rollout step toward gating
verification on a model: run the predictor silently, build up live accuracy, and
only later let the prediction skip work.

Shadow mode is **additive and opt-in**. When it is OFF (the default), proof
behaves exactly as before: identical ledger keys, identical verdict, identical
exit code, identical output. The shadow code path is a pure no-op until you turn
it on.

The predictor lives in the sibling `proofml` package (the scikit-learn research
layer). proof's core stays zero-dependency: it never imports proofml unless
shadow mode is enabled.

## What it does

On each verify (and each check), after proof has built the ledger entry but
before writing it, proof asks proofml for `P(deceptive)` on the primary claim.
That prediction, plus the raw behavioral signals it was based on, are written
into the same ledger line as the real verdict. Over a few hundred turns this
turns the ledger into a live labeled dataset: model prediction on one side, the
verifier's ground-truth verdict on the other.

## Enabling

Shadow runs IFF **either** of these is true:

- The env var `PROOFML_SHADOW` is truthy: one of `1`, `true`, `yes`
  (case-insensitive, surrounding whitespace ignored), or
- `.proof.toml` has a `[shadow]` table with `enabled = true`.

If neither is set, shadow is a no-op and the ledger entry is byte-for-byte
identical to pre-shadow proof. Default = OFF.

Env var:

```bash
export PROOFML_SHADOW=1
```

`.proof.toml`:

```toml
[shadow]
enabled = true
```

### Related env vars

These only matter when shadow is enabled.

| Var            | Purpose                                                                 |
| -------------- | ----------------------------------------------------------------------- |
| `PROOFML_MODEL`| Override the model file path. Default: `proofml/artifacts/model.joblib`. |
| `PROOFML_PATH` | Directory to add to `sys.path` so `import proofml` resolves in a prod install where proofml is not already importable. |

Model resolution precedence is `PROOFML_MODEL` > the packaged
`proofml/artifacts/model.joblib`. If no model file exists, prediction returns
nothing and the ledger entry is left unenriched (proof keeps working).

## What gets logged

Existing ledger keys are unchanged and always present:
`project`, `overall`, `n_claims`, `fails`, `claims`, `ts`.

When shadow is on and a prediction succeeds, these OPTIONAL keys are added to the
same line:

| key             | type  | meaning                                                |
| --------------- | ----- | ------------------------------------------------------ |
| `shadow_proba`  | float | `P(deceptive)` predicted before verifying, 0..1        |
| `shadow_model`  | str   | model name used                                        |
| `shadow_source` | str   | `transcript` (signals parsed from the session transcript) or `claim_only` (claim text only) |
| `behavior`      | dict  | the 6 raw behavioral signals (below)                   |

The `behavior` dict holds the raw signals, not the featurized vector, so a
dataset builder can re-featurize later with zero drift:

```json
{
  "ran_test_cmd": false,
  "claimed_without_running": true,
  "diff_lines": 42,
  "touched_test_files": false,
  "hedged": false,
  "absolute": true
}
```

When `proof verify` runs, the session transcript is available, so
`shadow_source` is usually `transcript` and the behavioral signals are real.
`proof check` runs claim-only, so its shadow rows are `claim_only` with neutral
behavioral defaults.

## The zero-impact-when-off guarantee

When shadow is OFF:

- proof does not import proofml at all. The trigger is checked first; a negative
  result returns immediately.
- The ledger entry has only the existing keys.
- Verdict, exit code, and printed output are unchanged.

When shadow is ON, the prediction is wrapped so it can never affect the result:

- The shadow predictor never raises. On any problem (missing model, missing
  scikit-learn or joblib, unreadable transcript, malformed model) it returns
  nothing and proof simply skips the enrichment.
- The proof-side call is itself wrapped in the same guard the ledger write uses,
  so even an unexpected failure cannot change the verdict or exit code.

Existing ledger consumers (`compute_stats`) read only
`overall` / `fails` / `claims` / `ts`, so the extra keys never disturb them.

## Rollout: shadow first, gate later

1. **Shadow first.** Turn shadow on and change nothing else. proof logs
   `shadow_proba` next to the verifier's real verdict on every turn. After a few
   hundred turns you have live accuracy, not just held-out accuracy. Measure it
   with `proofml dataset report` (see the proofml README).
2. **Gate second.** Once the shadow numbers justify it, skip verification when
   `P(deceptive)` is below the operating-point threshold the cascade printed.
   Keep a random audit sample always-verified so you keep measuring drift.

Building the labeled dataset and reading live accuracy are covered in the
proofml README under "Shadow mode": `proofml dataset build` and
`proofml dataset report`.
