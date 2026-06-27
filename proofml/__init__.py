"""proofml: a deception predictor for proof.

Learns to predict, from an agent's success claim plus behavioral signals,
whether the claim is deceptive, before running proof's expensive verifier.

Public modules:
    proofml.schema   canonical Example row + ledger mapping
    proofml.data     load/write Examples and the examples.jsonl interchange
    proofml.features feature extraction shared by train/cascade/benchmark
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
