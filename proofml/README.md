<div align="center">

# proofml

### Catch the lie before you pay to check it.

**A calibrated deception predictor that learns when an AI agent is bluffing about "all done, tests pass" so you can skip the expensive verifier on the claims that are obviously honest.**

[![Python](https://img.shields.io/badge/python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.9-F7931E?logo=scikitlearn&logoColor=white)](https://scikit-learn.org/)
[![tests](https://img.shields.io/badge/tests-63%20passing-2ea44f)](#tests)
[![held-out PR-AUC](https://img.shields.io/badge/held--out%20PR--AUC-0.976-8A2BE2)](#results-on-synthetic-data)
[![core](https://img.shields.io/badge/proof%20core-zero%20dependency-555)](https://github.com/EricFinland/proof)

</div>

---

proofml is the machine learning research layer on top of [**proof**](https://github.com/EricFinland/proof), the honesty verifier for coding agents. proof tells you *after the fact* whether an agent's "all done, tests pass" claim survived an independent verifier. proofml learns to predict that verdict *before* you pay for the verification, and quietly turns proof's ledger into a labeled honesty dataset while it does.

> ### The one-line thesis
> **Agents don't reveal lies in their claim text. They reveal them in their behavior.**
>
> "All tests pass" reads identically whether it is true or false. The signal is not in the sentence. It lives in the gap between what the agent *said* and what it actually *did*: did it run the test command before declaring victory, did the diff even touch the code under test, did it hedge. proofml's whole job is to read that gap.

proofml is a **sibling package** to proof. proof's core stays strictly zero dependency, so installing the tool never drags scikit-learn along. proofml is where the numpy and sklearn live, opt-in and bolted on the side.

---

## Why this is interesting

Most "is the AI lying" demos throw a transformer at the claim text and call it a day. That is exactly the thing that does not work here, and proofml proves it: when the claim string is the only input, the model is a coin flip. The interesting engineering is everything around that fact.

- **A real ML systems contribution, not a toy classifier.** The headline is not "I trained a model." It is the **cost-gated cascade**: a calibrated probability used as a cheap gate that skips expensive verification on claims it is confident about, with a measured frontier and a chosen operating point.
- **Calibration is load bearing.** The cascade decides on a *probability*, not a label, so the model is calibrated (Brier 0.073) and every claim of safety is backed by a reliability curve, not just accuracy.
- **It is wired back into the real tool, safely.** Two integration modes (shadow and gate) plug into proof's Stop hook. Both are opt-in, both fail toward verifying, and proof behaves byte for byte identically when they are off.
- **It is honest about its own limits.** The shipped numbers are on synthetic data, and the README says so loudly. The path to real numbers (and the extractor that gets you there) is part of the package.

---

## How it all fits together

```mermaid
flowchart TB
    A["AI coding agent<br/>claims: all tests pass"] --> HOOK{{"proof Stop hook"}}

    HOOK -->|"gate ON and<br/>confident honest"| SKIP["skip the verifier<br/>save the cost"]
    HOOK -->|"otherwise (default)"| VER["independent verifier<br/>runs the real checks"]

    VER --> LED[("honesty ledger<br/>~/.proof/ledger.jsonl")]
    SKIP -.->|"logged"| GATELOG[("gate.jsonl")]

    LED --> PML

    subgraph PML["proofml"]
        direction LR
        SCH["schema + data"] --> FEAT["features"]
        FEAT --> TRAIN["train<br/>calibrated baselines"]
        TRAIN --> MODEL[["model.joblib"]]
        MODEL --> CAS["cascade<br/>cost frontier"]
        MODEL --> BEN["benchmark<br/>ProofBench"]
        CAS --> OP[["operating_point.json"]]
    end

    MODEL -.->|"predicts on the next claim"| HOOK
    OP -.->|"calibrated threshold"| HOOK

    classDef store fill:#1f2937,stroke:#4b5563,color:#e5e7eb;
    classDef proofml fill:#2e1065,stroke:#7c3aed,color:#ede9fe;
    class LED,GATELOG,MODEL,OP store;
```

The loop closes on itself: proof produces labeled outcomes, proofml learns from them, and the learned model feeds back into proof's hook to decide what is worth verifying next.

---

## What's here

| Module          | Job |
| --------------- | --- |
| `schema.py`     | The canonical `Example` row, and the single place that maps proof's real ledger keys. |
| `data.py`       | Load the ledger, drop INCONCLUSIVE rows, read and write the `examples.jsonl` interchange format. |
| `synth.py`      | Bootstrap balanced labels by controlling repo state. Real labels come from the verifier. |
| `features.py`   | Interpretable claim and behavioral features on one shared featurization path. |
| `train.py`      | Calibrated logistic regression and gradient boosting baselines, picked by PR-AUC, with full eval. |
| `cascade.py`    | The cost-gated verification frontier. This is the ML systems contribution. |
| `benchmark.py`  | A versioned, checksummed ProofBench with per-category scoring and a leaderboard line. |
| `extract.py`    | The real Claude Code transcript feature extractor (`ran_test_cmd` / `diff_lines` parser). |
| `shadow.py`     | The live predictor proof calls to log a prediction next to each verdict. |
| `dataset.py`    | Turn the enriched ledger into real training data, and report live accuracy and gate safety. |

### The real ledger schema

proof's ledger writes one JSON object per line:

```json
{"project": "myrepo", "overall": "fail", "n_claims": 1, "fails": ["tests"], "claims": ["All done, tests pass."], "ts": 1781263949.53}
```

`schema.py` maps that exactly. It explodes each entry into one `Example` per claim string, labels `overall == "fail"` as **deceptive (1)** and `pass` as **honest (0)**, and drops `inconclusive` rows. The label is the ground truth proof already paid to compute.

---

## The training pipeline

```mermaid
flowchart LR
    L[("ledger.jsonl<br/>real but small")] --> EX
    S["synth.py<br/>balanced bootstrap"] --> EX["examples.jsonl"]
    EX --> F["features.py<br/>8 interpretable signals"]
    F --> T["train.py"]
    T --> M[["model.joblib<br/>calibrated"]]
    T --> H[["heldout.jsonl<br/>untouched test set"]]
    M --> C["cascade.py"]
    H --> C
    C --> PNG[["cascade.png<br/>+ operating_point.json"]]
    M --> B["benchmark.py"]
    EX --> B
    B --> BENCH[["proofbench_v1<br/>checksummed"]]

    classDef art fill:#0b3d2e,stroke:#10b981,color:#d1fae5;
    class M,H,PNG,BENCH art;
```

### Reproduce in one go

```bash
pip install -r requirements.txt
make all        # synth -> train -> cascade -> benchmark
```

No `make` (for example on Windows)? Run the steps directly from the directory that contains `proofml/` so `python -m proofml.X` resolves (set `PYTHONPATH` to that directory if needed):

```bash
python -m proofml.synth     --pairs 60 --out proofml/data/examples.jsonl --no-verifier
python -m proofml.train     --data proofml/data/examples.jsonl --out proofml/artifacts
python -m proofml.cascade   --artifacts proofml/artifacts --data proofml/data/examples.jsonl --min-recall 0.95
python -m proofml.benchmark freeze --data proofml/data/examples.jsonl --out proofml/bench/proofbench_v1.jsonl
python -m proofml.benchmark score  --bench proofml/bench/proofbench_v1.jsonl --model proofml/artifacts/model.joblib
```

Drop `--no-verifier` once proof is on PATH and `synth.py` will get **real labels** from `proof check --json` instead of controlled-state labels.

---

## The features: where the signal actually lives

Eight interpretable features, no black box. Every one is explainable in an interview, and every behavioral feature degrades gracefully to a neutral default on a ledger-only row so the model still trains on thin data.

| Feature | Kind | Why it matters |
| --- | --- | --- |
| `claimed_without_running` | behavioral | **The top signal.** Declared success but never ran the check. |
| `ran_test_cmd` | behavioral | A real test or build command actually executed before the claim. |
| `diff_lines` | behavioral | Size of the change (log scaled). A one-line "fix" with a big claim is suspicious. |
| `touched_test_files` | behavioral | Did the diff even touch the tests it says pass. |
| `hedged` | claim text | "should pass", "I think it works". |
| `absolute` | claim text | "all tests pass", "done". |
| `claim_len` | claim text | Raw length of the claim. |
| `n_test_words` | claim text | Count of test / pass / build tokens. |

The two claim-text-only features carry almost no weight on their own. That is the thesis, made measurable.

---

## Results on synthetic data

Numbers from a clean `make all` run (Python 3.14, scikit-learn 1.9, 120 synthetic rows, seed 1337):

| Metric | Value | Notes |
| --- | --- | --- |
| **PR-AUC** (held-out, 36 rows) | **0.976** | chosen model: `logistic_regression` |
| ROC-AUC | 0.972 | |
| **Brier** | **0.073** | well calibrated, which the cascade depends on |
| precision / recall / F1 | 0.944 | at the 0.5 label threshold |
| gradient boosting PR-AUC | 0.869 | the runner-up on the same split |

The cascade scores the **exact rows `train.py` held out**. `train.py` persists them to `artifacts/heldout.jsonl` and `cascade.py` reads that file, so the frontier is the model's genuine untouched test set, not a re-derived split. This is a deliberate honesty fix: an earlier version re-derived the split and quietly scored a different set of rows.

### The cost-gated cascade (the headline result)

Running the full verifier is expensive (booting servers, running suites). The predictor lets you skip verification on the claims it is confident are honest. Sweep the probability threshold and you get a frontier between **cost saved** and **lies still caught**:

```
threshold   verifier runs skipped   lies caught
  0.00              0%                 100%
  0.08             14%                 100%
  0.147            33%                 100%   <-- operating point (min-recall 0.95)
  0.47             50%                  94%
  0.58             56%                  83%
  0.88             81%                  39%
```

At the chosen operating point (held-out, 18 deceptive rows, min-recall 0.95):

> **Skip 33% of verifier runs while still catching 100% of the lies (18 of 18).**

That single curve is the headline. It is the difference between "I trained a classifier" and "I built a system that decides what is worth checking." The full frontier is rendered to `artifacts/cascade.png`, and the chosen point is written to `artifacts/operating_point.json` for the live gate to read.

---

## Real data: the transcript extractor

A personal ledger is small and PASS heavy, so the interesting signal comes from real session transcripts. `extract.py` parses a Claude Code session `.jsonl` and derives the behavioral features for real:

```bash
python -m proofml.extract --transcript path/to/session.jsonl \
    --ledger ~/.proof/ledger.jsonl --project myrepo --out proofml/data/real.jsonl
```

It extracts `ran_test_cmd` (a Bash tool call matching pytest / npm test / cargo test / go test and friends before the claim), `claimed_without_running` (the claim asserts success but no qualifying test ran), `diff_lines` and `touched_test_files` (from Edit / Write / MultiEdit tool calls), and hedged versus absolute claim language. Labels are attached only when a ledger row matches on project and nearest timestamp. Otherwise the row is emitted **unlabeled** for inference. It never fabricates a label.

This extractor is the part a reviewer will poke at hardest, so it is robust to malformed lines and string-versus-list message content, and it has its own tests.

---

## Integration mode 1: shadow mode

Shadow mode lets proof log a deception prediction next to every real verdict **without changing what proof does**. It is additive and opt-in. When it is off (the default), proof behaves exactly as before and its core never even imports proofml.

```mermaid
sequenceDiagram
    participant A as Agent
    participant H as proof Stop hook
    participant V as Verifier
    participant M as proofml.shadow
    participant L as ledger.jsonl

    A->>H: "all tests pass"
    H->>V: run the real checks
    V-->>H: verdict (pass / fail)
    H->>M: predict_now(claim, transcript)
    M-->>H: p(deceptive) + raw behavior
    H->>L: one line: verdict AND shadow_proba AND behavior
    Note over L: prediction on one side,<br/>ground truth on the other
```

### Enable

```bash
export PROOFML_SHADOW=1
```
```toml
[shadow]
enabled = true
```

Two related env vars apply only when shadow is on: `PROOFML_MODEL` overrides the model path (default `proofml/artifacts/model.joblib`), and `PROOFML_PATH` adds a directory to `sys.path` so `import proofml` resolves in a prod install. The zero-impact-when-off guarantee is documented in proof's `references/shadow-mode.md`.

### What it logs

The existing keys (`project, overall, n_claims, fails, claims, ts`) are untouched. Shadow adds `shadow_proba`, `shadow_model`, `shadow_source` (`transcript` or `claim_only`), and a `behavior` dict of the six raw signals. Over a few hundred turns the ledger becomes a **live labeled dataset**.

### Turn the ledger into data and measure live accuracy

```bash
python -m proofml.dataset build  --ledger ~/.proof/ledger.jsonl --out proofml/data/real.jsonl [--include-thin]
python -m proofml.dataset report --ledger ~/.proof/ledger.jsonl
```

`build` emits one `Example` per claim for entries with `overall` in `{pass, fail}`. Entries with a `behavior` dict become FEATURED rows; the rest are THIN rows, written only with `--include-thin`. `report` scores past shadow predictions against what actually happened and prints live PR-AUC, Brier, accuracy@0.5, and a bucketed calibration table. If scikit-learn is missing it still reports accuracy and Brier and skips PR-AUC.

---

## Integration mode 2: gating (cost saving)

Gating is the cascade applied live. proof's Stop hook can **skip** the expensive verifier when the model predicts a claim is honest. This is the only path in the whole system that can suppress verification, so it is built to fail safe at every step.

```mermaid
flowchart TD
    START["claim detected,<br/>proof is about to verify"] --> EN{"gate enabled?"}
    EN -->|no| VERIFY["VERIFY<br/>(normal proof behavior)"]
    EN -->|yes| FIRST{"first check?<br/>(no prior outcome)"}
    FIRST -->|"no, already failed once"| VERIFY
    FIRST -->|yes| PRED{"predict p(deceptive)"}
    PRED -->|"error / no model / no proba"| VERIFY
    PRED -->|"p >= threshold (risky)"| VERIFY
    PRED -->|"p < threshold (honest)"| AUDIT{"audit roll<br/>random < audit_rate?"}
    AUDIT -->|yes| VERIFY
    AUDIT -->|no| SKIP["SKIP the verifier"]

    classDef safe fill:#0b3d2e,stroke:#10b981,color:#d1fae5;
    classDef danger fill:#3b0764,stroke:#a855f7,color:#f3e8ff;
    class VERIFY safe;
    class SKIP danger;
```

Read that diagram once and the safety model is obvious: **every path leads to VERIFY except a confident, non-audited, first-time honest claim.** A bug, a missing model, or an unreadable threshold can never cause a skip. It can only ever cost you a verification you did not strictly need.

> ### Do NOT enable gating for real work until the model is retrained on REAL data.
> The shipped model is trained on synthetic rows and is for wiring and testing only. Skipping verification on a synthetic model's confidence trusts a model that has never seen your transcripts. Run shadow mode, build a real labeled dataset, retrain, recompute the operating point, and only then consider turning the gate on.

### Enable

```bash
export PROOFML_GATE=1
```
```toml
[gate]
enabled = true
threshold = 0.1
audit_rate = 0.1
```

Gating runs independently of shadow mode, so you can gate with or without shadow logging on.

### The two knobs

- **`threshold`** is the `P(deceptive)` cutoff. `proba >= threshold` verifies, below it is a skip or audit candidate. Resolution order: `PROOFML_GATE_THRESHOLD` env, then `.proof.toml [gate].threshold`, then `artifacts/operating_point.json` (the calibrated value the cascade writes), then default `0.1`.
- **`audit_rate`** (clamped to `[0, 1]`) is the fraction of predicted-honest claims still verified anyway as a sampled audit. Those audits are the ground truth that confirms the skips were safe. Same resolution order with `PROOFML_GATE_AUDIT_RATE`.

Every enabled decision is appended to `gate.jsonl` in the marker root (`PROOF_HOME` or `~/.proof`).

### Confirm it is safe

```bash
python -m proofml.dataset gate --gate ~/.proof/gate.jsonl --ledger ~/.proof/ledger.jsonl
```

This reports total decisions, skip / verify / audit counts, the **SKIP RATE** (fraction of verifier runs saved), mean `proba` by decision, and the number that matters most, the **audit-slice miss rate**: of the claims predicted honest but verified anyway, how many turned out to be lies. A non-zero miss rate means the gate is skipping real lies and the threshold is too loose (or the model needs retraining). That single number is how you keep the gate honest in production.

Full safety model, log schema, and resolution order live in proof's `references/gating.md`.

---

## Rollout order

```mermaid
flowchart LR
    S1["1. Shadow mode<br/>log predictions,<br/>change nothing"] --> S2["2. Build real dataset<br/>+ retrain"]
    S2 --> S3["3. Recompute<br/>operating point"]
    S3 --> S4["4. Gate, with a<br/>non-zero audit slice"]
    S4 -->|"watch miss rate"| S4
```

1. **Shadow first.** Enable shadow and change nothing else. `dataset report` shows live accuracy, not just held-out accuracy.
2. **Gate second.** Once shadow numbers justify it, enable the gate, set `threshold` from the recomputed `operating_point.json`, and keep `audit_rate` non-zero. Watch `dataset gate` for the audit-slice miss rate so you keep measuring drift.

---

## The honest caveats (put these in any writeup, do not hide them)

- A personal ledger is small and imbalanced. `synth.py` exists to bootstrap, and the interesting result is the **cascade frontier**, not a leaderboard number on synthetic data.
- The synthetic behavioral signal is injected with deliberate noise (about 83% correlation, with flips) so it is learnable without being trivially leaked. On real transcripts you must extract `ran_test_cmd`, `diff_lines`, and the rest for real. `extract.py` is that piece.
- `synth.py` draws claim *text* independently of the label, so the model cannot cheat off phrasing. That means the absolute-versus-hedged category gap on the synthetic set is noise, not a finding. Any real "hedged claims are harder" claim has to come from real labeled data.
- The `benchmark score` numbers are computed over the full frozen set, which includes training rows, so they reflect in-sample fit. The honest generalization number is the held-out PR-AUC from `train.py` (0.976 here).
- Calibration is load bearing. The cascade decides on probabilities, so always report Brier score and a reliability curve, not just accuracy.

---

## Tests

```bash
python -m pytest proofml -q     # 63 tests; numpy + scikit-learn required
```

The proof side has its own suite that stays green with shadow and gate both off, proving the integration is genuinely additive.

## Project layout

```
proofml/
  schema.py  data.py  features.py        # the contract
  synth.py   extract.py                  # data in
  train.py   cascade.py  benchmark.py    # model, frontier, bench
  shadow.py  dataset.py                  # live integration + real-data tooling
  artifacts/                             # model.joblib, heldout.jsonl, operating_point.json, cascade.png
  bench/                                 # frozen, checksummed ProofBench
  tests/                                 # 63 tests
  INTEGRATION.md  GATING.md              # the integration contracts
```

## License

Part of the [proof](https://github.com/EricFinland/proof) repository and shares its license.
