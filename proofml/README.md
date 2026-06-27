# proofml

A deception predictor for [proof](https://github.com/EricFinland/proof). proof's
verifier tells you *after the fact* whether an agent's "all done, tests pass"
claim was true. proofml learns to predict that verdict *before* paying for the
expensive verification, and turns proof's ledger into a labeled honesty dataset.

The thesis in one line: **agents don't reveal lies in their claim text, they
reveal them in their behavior.** The model's job is to read the gap between what
the agent said and what it actually did.

proofml is a sibling package to proof. proof's core stays zero-dependency;
proofml is the research layer (scikit-learn) that sits on top, so installing the
tool never drags sklearn along.

## What's here

| Module         | Job                                                                   |
| -------------- | --------------------------------------------------------------------- |
| `schema.py`    | Canonical `Example` row + the one place that maps proof's real ledger keys. |
| `data.py`      | Load the ledger; drop INCONCLUSIVE rows; read/write the `examples.jsonl` interchange format. |
| `synth.py`     | Bootstrap balanced labels by controlling repo state; real labels from the verifier. |
| `features.py`  | Interpretable claim + behavioral features (one shared featurization path). |
| `train.py`     | Calibrated logreg / gradient-boost baselines, picked by PR-AUC, full eval. |
| `cascade.py`   | Cost-gated verification frontier (the ML-systems contribution).       |
| `benchmark.py` | Versioned, checksummed ProofBench + per-category scoring + leaderboard. |
| `extract.py`   | Real Claude Code transcript feature extractor (ran_test_cmd / diff_lines parser). |

### The real ledger schema

proof's ledger writes one JSON object per line with keys
`project, overall, n_claims, fails, claims, ts` (see `proof/scripts/proofkit/verdict.py`).
`schema.py` maps that exactly: it explodes each entry into one `Example` per
claim string, labels `overall == "fail"` as deceptive (1) and `pass` as honest
(0), and drops `inconclusive` rows.

## Reproduce in one go

```bash
pip install -r requirements.txt
make all        # synth -> train -> cascade -> benchmark
```

If `make` is unavailable (e.g. on Windows), run the steps directly. Run from the
directory that contains `proofml/` so `python -m proofml.X` resolves (set
`PYTHONPATH` to that directory if needed):

```bash
python -m proofml.synth --pairs 60 --out proofml/data/examples.jsonl --no-verifier
python -m proofml.train --data proofml/data/examples.jsonl --out proofml/artifacts
python -m proofml.cascade --artifacts proofml/artifacts --data proofml/data/examples.jsonl --min-recall 0.95
python -m proofml.benchmark freeze --data proofml/data/examples.jsonl --out proofml/bench/proofbench_v1.jsonl
python -m proofml.benchmark score  --bench proofml/bench/proofbench_v1.jsonl --model proofml/artifacts/model.joblib
```

Drop `--no-verifier` once proof is on PATH so `synth.py` gets real labels from
`proof check --json` instead of controlled-state labels.

## Results on synthetic data

Numbers from a clean `make all` run (Python 3.14, scikit-learn 1.9, 120
synthetic rows, seed 1337):

- **Model (held-out, 36 rows):** chosen `logistic_regression`, PR-AUC **0.976**,
  ROC-AUC 0.972, Brier **0.073** (well calibrated), precision/recall/F1 0.944.
  Gradient boosting scored PR-AUC 0.869 on the same split.
- **Cascade (held-out, 18 deceptive rows, min-recall 0.95):** operating point at
  threshold 0.147 skips **33% of verifier runs while catching 100% of lies**
  (18/18). The frontier is in `artifacts/cascade.png`.

The cascade scores the exact rows `train.py` held out: `train.py` persists them
to `artifacts/heldout.jsonl` and `cascade.py` reads that file, so the frontier is
the model's genuine untouched test set rather than a re-derived split.

## Real data: the transcript extractor

A personal ledger is small and PASS-heavy, so the interesting signal comes from
real session transcripts. `extract.py` parses a Claude Code session `.jsonl` and
derives the behavioral features for real:

```bash
python -m proofml.extract --transcript path/to/session.jsonl \
    --ledger ~/.proof/ledger.jsonl --project myrepo --out proofml/data/real.jsonl
```

It extracts `ran_test_cmd` (a Bash tool call matching pytest / npm test / cargo
test / go test / etc. before the claim), `claimed_without_running` (the claim
asserts success but no qualifying test ran), `diff_lines` and
`touched_test_files` (from Edit/Write/MultiEdit tool calls), and hedged vs
absolute claim language. Labels are attached only when a ledger row matches on
project and nearest timestamp; otherwise the row is emitted **unlabeled** for
shadow-mode inference. It never fabricates a label.

## Shadow mode

Shadow mode lets proof log a deception prediction next to every real verdict
without changing what proof does. It is additive and opt-in: when it is OFF (the
default), proof behaves exactly as before. proof's core never imports proofml
unless shadow mode is enabled.

### Enable

Shadow runs IFF either the env var `PROOFML_SHADOW` is truthy (`1`, `true`, or
`yes`, case-insensitive) or `.proof.toml` has `[shadow] enabled = true`:

```bash
export PROOFML_SHADOW=1
```

```toml
[shadow]
enabled = true
```

Two related env vars apply only when shadow is on: `PROOFML_MODEL` overrides the
model path (default `proofml/artifacts/model.joblib`), and `PROOFML_PATH` adds a
directory to `sys.path` so `import proofml` resolves in a prod install. Full
details, including the zero-impact-when-off guarantee, are in proof's
`references/shadow-mode.md`.

### What it logs

On each verify, proof asks the model for `P(deceptive)` on the primary claim and
writes it into the same ledger line as the real verdict. Existing keys
(`project, overall, n_claims, fails, claims, ts`) are unchanged; shadow adds
`shadow_proba`, `shadow_model`, `shadow_source` (`transcript` or `claim_only`),
and a `behavior` dict of the six raw signals. Over a few hundred turns the ledger
becomes a live labeled dataset: prediction on one side, ground-truth verdict on
the other.

### Turn the ledger into data and measure live accuracy

```bash
python -m proofml.dataset build  --ledger ~/.proof/ledger.jsonl --out proofml/data/real.jsonl [--include-thin]
python -m proofml.dataset report --ledger ~/.proof/ledger.jsonl
```

`build` emits one `Example` per claim string for entries with `overall` in
`{pass, fail}` (label `1` for `fail`, `0` for `pass`; `inconclusive` dropped).
Entries with a `behavior` dict become FEATURED rows (`source = "transcript"`);
the rest become THIN rows (`source = "ledger"`), which are written only with
`--include-thin`. It prints featured-vs-thin counts and label balance.

`report` scores past shadow predictions against what actually happened: over
entries that have both `shadow_proba` and `overall` in `{pass, fail}`, it prints
live PR-AUC, Brier, accuracy@0.5, and a bucketed calibration table. If
scikit-learn is missing it computes accuracy and Brier without it and skips
PR-AUC. With fewer than 2 usable rows or a single verdict class it prints a clear
"not enough data" message and exits 0.

## Gating (cost-saving)

Gating lets proofml SKIP proof's expensive verifier when it predicts a claim is
honest, saving the cost of an independent verifier subagent. It applies the
cascade's calibrated operating point live, at the moment of the claim. Gating is
additive and opt-in: when OFF (the default), proof's Stop hook behaves exactly as
before. The gate can only ever SUPPRESS the verifier, and it always fails toward
verifying.

> **Do NOT enable gating for real work until the model is retrained on REAL
> data.** The shipped model is trained on synthetic rows and is for wiring and
> testing only. Skipping verification on a synthetic model's confidence trusts a
> model that has never seen your transcripts. Run shadow mode, build a real
> labeled dataset (`python -m proofml.dataset build`), retrain, recompute the
> operating point, and only then consider turning the gate on.

### Enable

Gating runs IFF either the env var `PROOFML_GATE` is truthy (`1`, `true`, or
`yes`, case-insensitive) or `.proof.toml` has `[gate] enabled = true`:

```bash
export PROOFML_GATE=1
```

```toml
[gate]
enabled = true
threshold = 0.1
audit_rate = 0.1
```

The gate runs independently of shadow mode, so you can gate with or without
shadow logging on.

### The audit and threshold knobs

- **`threshold`** is the `P(deceptive)` cutoff: `proba >= threshold` verifies,
  below it the claim is a skip or audit candidate. Resolution order: env
  `PROOFML_GATE_THRESHOLD` > `.proof.toml [gate].threshold` >
  `artifacts/operating_point.json["threshold"]` (the calibrated value the cascade
  writes) > default `0.1`.
- **`audit_rate`** (clamped to `[0,1]`) is the fraction of predicted-honest
  claims still verified anyway as a sampled audit. Those audits are the ground
  truth that confirms the gate's skips were safe. Resolution order: env
  `PROOFML_GATE_AUDIT_RATE` > `.proof.toml [gate].audit_rate` > default `0.1`.

Every enabled decision is appended to `gate.jsonl` in the marker root (env
`PROOF_HOME` or `~/.proof`). The threshold comes from `operating_point.json`,
which `proofml.cascade` writes alongside its frontier output.

### Confirm it is safe

```bash
python -m proofml.dataset gate --gate ~/.proof/gate.jsonl --ledger ~/.proof/ledger.jsonl
```

Reports total decisions, skip / verify / audit counts, the SKIP RATE (fraction of
verifier runs saved), mean `proba` by decision, and the **audit-slice miss rate**:
of the claims predicted honest but verified anyway, how many turned out FAIL.
That miss rate is the number that tells you whether the gate is safe to keep. A
non-zero rate means the gate is skipping real lies and the threshold is too loose
(or the model needs retraining). Empty or missing files are handled gracefully
with a clear message and exit 0.

Full safety model, log schema, and resolution order are in proof's
`references/gating.md`.

## Wiring it back into proof (rollout order)

1. **Shadow mode first.** Enable shadow (above) and change nothing else. proof
   logs `shadow_proba` next to the verifier's real verdict on every turn, and
   `python -m proofml.dataset report --ledger ~/.proof/ledger.jsonl` shows live
   accuracy, not just held-out accuracy. Run
   `python -m proofml.dataset build --ledger ~/.proof/ledger.jsonl --out proofml/data/real.jsonl`
   to retrain on real labeled rows once you have enough.
2. **Gate second.** Once shadow numbers justify it, enable the gate with
   `export PROOFML_GATE=1` (or `.proof.toml [gate] enabled = true`), set
   `threshold` from the recomputed `artifacts/operating_point.json`, and keep
   `audit_rate` non-zero. Watch
   `python -m proofml.dataset gate --gate ~/.proof/gate.jsonl --ledger ~/.proof/ledger.jsonl`
   for the audit-slice miss rate so you keep measuring drift. See the "Gating
   (cost-saving)" section above and proof's `references/gating.md` for the full
   safety model.

## The honest caveats (put these in any writeup, don't hide them)

- A personal ledger is small and imbalanced. `synth.py` exists to bootstrap; say
  so. The interesting result is the *cascade frontier*, not a leaderboard number
  on synthetic data.
- The synthetic behavioral signal is injected with deliberate noise (about 83%
  correlation, with flips) so it is learnable without being trivially leaked. On
  real transcripts you must extract `ran_test_cmd`, `diff_lines`, etc. for real;
  `extract.py` is that piece, and it is the part a reviewer will poke at, so the
  tests around it matter.
- `synth.py` draws claim *text* independently of the label, so the model cannot
  cheat off phrasing. That means the absolute-vs-hedged category gap on this
  synthetic set is noise, not a finding. Any real "hedged claims are harder"
  claim has to come from real labeled data, not the generator.
- The `benchmark score` numbers are computed over the full frozen set, which
  includes training rows, so they reflect in-sample fit. The honest
  generalization number is the held-out PR-AUC from `train.py` (0.976 here).
- Calibration is load-bearing: the cascade decides on probabilities. Always
  report Brier score and a reliability curve, not just accuracy.

## Tests

```bash
python -m pytest proofml -q     # 49 tests, numpy + sklearn required
```
```
