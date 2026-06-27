# Cost-Gated Verification (gating)

Gating lets proofml SKIP proof's expensive verifier when it is confident an
agent's "all done, tests pass" claim is honest. It is the cascade's calibrated
operating point applied live, at the moment of the claim.

Today proof's Stop hook (`proof_trigger.py`) BLOCKS whenever an agent claims work
is complete, which forces an independent verifier subagent to run. That is the
expensive step. With gating ON, proofml predicts `P(deceptive)` for the claim
first, and if the prediction is well below the operating-point threshold, the
hook returns without blocking, so the verifier never runs and you save the cost.

Gating is **additive and opt-in**. When it is OFF (the default), proof behaves
exactly as before: identical block decisions, identical output, identical exit
codes. proofml is never imported on the OFF path. The gate can only ever SUPPRESS
the verifier; it never changes the verify path itself, the real-verdict ledger
schema, or any non-gated behavior.

> **Do NOT enable gating for real work until the model is retrained on REAL
> data.** The shipped model is trained on synthetic rows from `synth.py` and is
> for wiring and testing only. Skipping verification on a synthetic model's
> confidence means trusting a model that has never seen your actual transcripts.
> The correct order is: run shadow mode (see `shadow-mode.md`), build a real
> labeled dataset (`python -m proofml.dataset build`), retrain, recompute the
> operating point with the cascade, and only then consider turning the gate on.
> Until then, leave gating OFF.

## The safety model

Gating is the one place in proof that can suppress the verifier, so every part of
it is built to fail toward verifying. Five guarantees:

1. **Opt-in.** The gate runs only when you explicitly enable it (below). Default
   OFF. When OFF, the decision function returns immediately, proofml is never
   imported, and nothing is logged.
2. **Fail-safe to verify.** Any uncertainty means VERIFY. If the predictor
   errors, the model file is missing, the probability is `None` or unparseable,
   proofml cannot import, or anything else goes wrong, the gate falls through to
   normal blocking. It NEVER skips on error, and the decision function NEVER
   raises. A bug can only ever cause an extra verification, never a missed one.
3. **Skip only the first check.** The gate may skip only a claim's FIRST
   verification. The hook reaches the gate only after `should_block(...)` already
   returned `True`, and it additionally requires `last_outcome(session, claim)`
   to be `None`. A re-verification after a prior fail or inconclusive is never
   skipped: once a claim has gone wrong, it is always re-verified.
4. **Random audit slice.** Even among claims predicted honest, a configurable
   fraction (`audit_rate`, default 10%) is still verified anyway. These audits
   are the ground truth that tells you whether the gate's skips were actually
   safe. They are how you keep measuring drift after rollout.
5. **Additive.** Gating never changes proof's verdict, exit code, or the
   real-verdict ledger keys. The only new artifact is `gate.jsonl`, a decision
   log that lives separate from the ledger.

### Confirm it is safe: `proofml dataset gate`

The number that says whether the gate is safe to keep is the **audit-slice miss
rate**: of the claims the gate predicted honest but verified anyway (the audit
slice), how many actually turned out to be FAIL? Those are misses the gate would
have wrongly skipped.

```bash
python -m proofml.dataset gate --gate ~/.proof/gate.jsonl --ledger ~/.proof/ledger.jsonl
```

It reports:

- total decisions, with counts of skip / verify / audit
- **SKIP RATE** = `skip / (skip + verify + audit)`, the fraction of verifier runs
  saved (the cost win)
- mean `proba` by decision
- **AUDIT-SLICE MISS RATE** (with `--ledger`): it joins each audited decision to
  its real verdict by `project` + claim text (prefix match, since the gate
  truncates the claim to 120 chars) + nearest `ts`, then reports how many audited
  claims turned out FAIL. A non-zero miss rate means the gate is skipping real
  lies and the threshold is too loose (or the model needs retraining).

Empty or missing files are handled gracefully with a clear message and exit 0.
Without `--ledger` it still prints skip rate and counts, just not the miss rate.
Read this report regularly once gating is on; it is the live safety check.

## Enable

Gating runs IFF **either** of these is true:

- the env var `PROOFML_GATE` is truthy (`1`, `true`, or `yes`, case-insensitive,
  surrounding whitespace ignored), OR
- `.proof.toml` has a `[gate]` table with `enabled = true`.

If neither is set, the gate is a no-op. Default = OFF.

Env var:

```bash
export PROOFML_GATE=1
```

`.proof.toml`:

```toml
[gate]
enabled = true
threshold = 0.1
audit_rate = 0.1
```

Gating works independently of shadow mode (`PROOFML_SHADOW`): the gate runs its
own trigger check and then calls the predictor directly, so you can gate without
shadow logging on, or run both.

## Threshold and audit-rate configuration

**Threshold** is the `P(deceptive)` cutoff. If `proba >= threshold` the gate
verifies (predicts risky); below it the claim is a skip or audit candidate. A
lower threshold is more conservative (verifies more). Resolution order, first
match wins:

1. env `PROOFML_GATE_THRESHOLD`
2. `.proof.toml` `[gate].threshold`
3. `artifacts/operating_point.json` `["threshold"]` (the calibrated value the
   cascade wrote; see below)
4. default `0.1`

The operating-point file is located via stdlib only (proofml is not imported for
this): the directory of env `PROOFML_MODEL` if set, else a sibling
`proofml/artifacts/operating_point.json` (also honoring `PROOFML_PATH`). A
missing or `null` threshold falls through to the next source, so the gate never
skips on a null threshold.

**Audit rate** is the fraction of predicted-honest claims that are still verified
as a sampled audit, clamped to `[0, 1]`. Resolution order:

1. env `PROOFML_GATE_AUDIT_RATE`
2. `.proof.toml` `[gate].audit_rate`
3. default `0.1`

Related env vars, shared with shadow mode: `PROOFML_MODEL` overrides the model
file path; `PROOFML_PATH` adds a directory to `sys.path` so `import proofml`
resolves in a prod install.

## The decision logic

When the gate is enabled and reaches a claim's first verification:

- get a prediction via the predictor (the same one shadow mode uses)
- if there is no prediction or the probability is unusable -> **verify**
  (fail-safe), logged with a `reason`
- if `proba >= threshold` -> **verify** (predicted risky)
- else (`proba < threshold`, predicted honest): roll `random.random()`; if the
  roll is below `audit_rate` -> **audit** (still verifies, sampled), otherwise
  -> **skip** (trust the claim, suppress the verifier)

Only `skip` suppresses the verifier. Both `verify` and `audit` block exactly as
proof does today.

## What `gate.jsonl` logs

The gate appends one JSON object per decision to `gate.jsonl` in the marker root
(env `PROOF_HOME` if set, else `~/.proof`). Every enabled decision path is logged
(skip, verify, audit); the OFF path logs nothing. Logging never raises; a logging
failure is swallowed so it can never affect the decision.

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

| key          | type                                   | notes                                          |
| ------------ | -------------------------------------- | ---------------------------------------------- |
| `ts`         | float                                  | epoch seconds, stamped if absent               |
| `project`    | str                                    | basename of the project root                   |
| `session`    | str                                    | proof session id                               |
| `claim`      | str (<= 120 chars)                     | truncated claim text                           |
| `proba`      | float or null                          | `P(deceptive)`; null on a predict failure      |
| `threshold`  | float                                  | resolved threshold                             |
| `audit_rate` | float                                  | resolved, clamped audit rate                   |
| `decision`   | `"skip"` / `"verify"` / `"audit"`      | the gate decision                              |
| `source`     | `"transcript"` / `"claim_only"` / null | prediction source                              |
| `behavior`   | dict (6 raw signals) or null           | raw signals behind the prediction              |
| `reason`     | str (optional)                         | e.g. `predict_failed`, `proba_none`, `gate_error` |

The `behavior` dict holds the raw signals, not the featurized vector, so you can
re-featurize later with zero drift. `gate.jsonl` is the input to
`proofml dataset gate`.

## Where the threshold comes from: `operating_point.json`

The threshold the gate reads in resolution step 3 is calibrated by the cascade.
`proofml.cascade.run_cascade` writes `artifacts/operating_point.json` additively
(the cascade's existing `cascade.png` / `cascade_frontier.csv` and metrics are
unchanged):

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

| key          | type          | meaning                                            |
| ------------ | ------------- | -------------------------------------------------- |
| `threshold`  | float or null | chosen `proba` cutoff; null if recall unreachable  |
| `min_recall` | float         | the recall floor used to pick the point            |
| `recall`     | float or null | recall on deception at the chosen threshold        |
| `skip_rate`  | float or null | fraction of verifier runs skipped at that point    |
| `model`      | str           | chosen model name                                  |
| `n_held`     | int           | held-out rows the frontier was computed on         |
| `n_lies`     | int or null   | deceptive rows in the held-out set                 |

When no operating point meets `min_recall`, the cascade writes `threshold: null`
and prints a note. The gate treats a null/missing threshold as "not available"
and falls back to the next resolution source or the default, so it never skips on
a null threshold.

This file is the bridge between the offline cascade and the live gate: pick the
threshold once, where you can see the full recall vs skip-rate frontier, and the
gate applies it at claim time.

## Rollout order

1. **Shadow first.** Turn shadow mode on (see `shadow-mode.md`) and change nothing
   else. proof logs `shadow_proba` next to the verifier's real verdict on every
   turn. Build live accuracy, retrain on real data, and recompute the operating
   point.
2. **Gate second.** Only once the shadow and audit numbers justify it, enable the
   gate with `PROOFML_GATE=1`, set a threshold from the recomputed
   `operating_point.json`, keep `audit_rate` non-zero, and watch
   `python -m proofml.dataset gate --gate ~/.proof/gate.jsonl --ledger ~/.proof/ledger.jsonl`
   for the audit-slice miss rate.

See also: `shadow-mode.md` (the prerequisite logging layer) and
`configuration.md` (full `.proof.toml` reference).
