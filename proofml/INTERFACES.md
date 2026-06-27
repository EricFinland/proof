# proofml foundation interfaces

The exact public surface of `schema`, `data`, and `features`. Parallel build
agents (train, cascade, benchmark, synth, extract) code against THIS. Do not
invent different names.

Package import: `import proofml.schema`, `proofml.data`, `proofml.features`.
Run modules with `python -m proofml.X` from the `proofml` parent directory.

## proofml.schema

```python
LEDGER_KEYS: dict   # {"claims","overall","fails","ts","project"} -> meaning

@dataclass
class Example:
    claim: str
    label: int                 # 1 = deceptive (claim false), 0 = honest. Never None.
    project: str = ""
    ts: float = 0.0
    source: str = "ledger"     # ledger | synth | transcript
    ran_test_cmd: bool = False
    claimed_without_running: bool = False   # TOP feature
    diff_lines: int = 0
    touched_test_files: bool = False
    hedged: bool = False
    absolute: bool = False

def from_ledger_entry(entry: dict) -> list[Example]
    # explodes one real ledger entry into one Example per claim string.
    # label = 1 if overall=="fail" else 0. Drops overall=="inconclusive" (-> []).
    # behavioral fields stay at defaults. source="ledger".
```

Real proof ledger entry shape (one JSON object per line, ~/.proof/ledger.jsonl):
```json
{"project": str, "overall": "pass"|"fail"|"inconclusive",
 "n_claims": int, "fails": [method,...], "claims": [str,...], "ts": float}
```

## proofml.data

```python
def load_ledger(path: str | None = None) -> list[Example]
    # reads ~/.proof/ledger.jsonl by default (PROOF_HOME env or ~/.proof, same
    # logic as proof's ledger.py). Skips corrupt lines. Drops inconclusive.

def load_examples(path: str) -> list[Example]
    # reads the examples.jsonl interchange (one asdict(Example) per line).
    # skips malformed lines and rows whose label is None / missing.

def write_examples(examples: list[Example], path: str) -> str
    # writes one json.dumps(asdict(Example)) per line. Creates parent dirs.
    # returns the path written.
```

examples.jsonl interchange format: one JSON object per line = `asdict(Example)`.
This is the shared format train/synth/extract/cascade/benchmark all use.

## proofml.features

```python
FEATURE_NAMES: list[str]   # stable, ordered. Current order:
#   ["claimed_without_running", "ran_test_cmd", "diff_lines_log",
#    "touched_test_files", "hedged", "absolute", "claim_len", "n_test_words"]

def featurize(ex: Example) -> dict[str, float]   # keys == FEATURE_NAMES
def to_matrix(examples: list[Example]) -> numpy.ndarray  # shape (n, len(FEATURE_NAMES))
def labels(examples: list[Example]) -> numpy.ndarray     # shape (n,), int
```

Notes for downstream:
- `diff_lines` is log-scaled into the `diff_lines_log` feature via `log1p`.
- `n_test_words` counts test/pass/build/green/check/lint tokens in the claim.
- Every behavioral feature is 0 for ledger-only rows. That is intended.
- train / cascade / benchmark MUST featurize via `proofml.features.to_matrix`
  so all three share one path.
