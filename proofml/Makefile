PY ?= python
DATA ?= data/examples.jsonl
ARTIFACTS ?= artifacts
BENCH ?= bench/proofbench_v1.jsonl
MIN_RECALL ?= 0.95
PAIRS ?= 60

.PHONY: all synth train cascade benchmark freeze score test clean

all: synth train cascade benchmark

synth:
	$(PY) -m proofml.synth --pairs $(PAIRS) --out $(DATA)

train:
	$(PY) -m proofml.train --data $(DATA) --out $(ARTIFACTS)

cascade:
	$(PY) -m proofml.cascade --artifacts $(ARTIFACTS) --data $(DATA) --min-recall $(MIN_RECALL)

benchmark: freeze score

freeze:
	$(PY) -m proofml.benchmark freeze --data $(DATA) --out $(BENCH)

score:
	$(PY) -m proofml.benchmark score --bench $(BENCH) --model $(ARTIFACTS)/model.joblib

test:
	$(PY) -m pytest -q

clean:
	rm -rf $(ARTIFACTS)/*.joblib $(ARTIFACTS)/*.json $(ARTIFACTS)/*.png $(ARTIFACTS)/*.csv
	rm -rf data/*.jsonl bench/*.jsonl bench/*.meta.json
	find . -type d -name __pycache__ -exec rm -rf {} +
