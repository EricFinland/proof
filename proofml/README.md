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

## Wiring it back into proof (rollout order)

1. **Shadow mode first.** In proof's Stop hook, run the model on the claim and
   log `predict_proba` next to the verifier's real verdict in the ledger. Change
   nothing else. After a few hundred turns you have live accuracy, not just
   held-out accuracy.
2. **Gate second.** Once shadow numbers justify it, skip verification when
   `p(deceptive) < threshold` (use the operating point `cascade.py` printed).
   Keep a random audit sample always-verified so you keep measuring drift.

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
