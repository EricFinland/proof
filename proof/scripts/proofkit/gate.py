"""Cost-gated verification: the live gate decision.

proof's Stop hook normally BLOCKS when an agent claims completion, forcing an
expensive verifier subagent. This module lets proofml SKIP that verification when
it is confident the claim is honest, applying the cascade's calibrated operating
point live. It is the only place in proofkit that decides to suppress the
verifier, so SAFETY is paramount:

  - OPT-IN: gating runs IFF env PROOFML_GATE is truthy OR .proof.toml [gate]
    enabled = true. Default OFF. When OFF, decide() returns None immediately and
    proofml is never imported, so proof behaves exactly as today.
  - FAIL-SAFE: any uncertainty => VERIFY. If the predictor errors, the model is
    missing, proba is None, proofml can't import, or anything is wrong, the gate
    falls through to normal blocking. It NEVER skips on error.
  - decide() NEVER raises.

This module imports stdlib only at import time. proofml is reached only lazily,
via proofkit.shadow.predict_now, and only after the gate trigger passes.
"""
import json
import os
import random
import time
from pathlib import Path


_TRUTHY = {"1", "true", "yes"}

_DEFAULT_THRESHOLD = 0.1
_DEFAULT_AUDIT_RATE = 0.1
_CLAIM_LIMIT = 120


def _env_truthy(name: str) -> bool:
    """True if env var `name` is set to a truthy value (case-insensitive)."""
    val = os.environ.get(name, "")
    return val.strip().lower() in _TRUTHY


def _config(root: str) -> dict:
    """Load .proof.toml as a dict. Never raises; returns {} on any failure."""
    try:
        from proofkit.config import load_config

        return load_config(root)
    except Exception:
        return {}


def is_enabled(root: str = ".") -> bool:
    """Whether gating is enabled via env var or .proof.toml. Never raises."""
    try:
        if _env_truthy("PROOFML_GATE"):
            return True
        from proofkit.config import cfg_get

        return cfg_get(_config(root), "gate", "enabled", default=False) is True
    except Exception:
        return False


def _marker_base(marker_root=None) -> Path:
    """Resolve the marker dir: explicit > $PROOF_HOME > ~/.proof. Mirrors marker.py."""
    if marker_root:
        return Path(marker_root)
    env = os.environ.get("PROOF_HOME", "")
    return Path(env) if env else Path.home() / ".proof"


def _operating_point(root: str) -> dict:
    """Read artifacts/operating_point.json. Never raises; returns {} on failure.

    The operating point lives next to the model. We locate it via the same
    precedence proofml.shadow uses for the model: env PROOFML_MODEL's directory,
    else the proofml/artifacts default. We resolve proofml/artifacts WITHOUT
    importing proofml (stdlib only): the package sits beside the proof package,
    so we walk up from this file to find a sibling proofml/artifacts dir, and
    also honor PROOFML_PATH.
    """
    candidates = []
    model_env = os.environ.get("PROOFML_MODEL", "")
    if model_env:
        try:
            candidates.append(Path(model_env).parent / "operating_point.json")
        except Exception:
            pass

    # PROOFML_PATH/proofml/artifacts/operating_point.json
    path_env = os.environ.get("PROOFML_PATH", "")
    if path_env:
        candidates.append(Path(path_env) / "proofml" / "artifacts" / "operating_point.json")

    # Walk up from this file looking for a sibling proofml/artifacts dir. proofkit
    # lives at .../proof/scripts/proofkit/gate.py; proofml is a sibling of proof.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "proofml" / "artifacts" / "operating_point.json")

    for cand in candidates:
        try:
            if cand.is_file():
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def _resolve_threshold(cfg: dict, root: str) -> float:
    """env PROOFML_GATE_THRESHOLD > [gate].threshold > operating_point.json > default."""
    # 1) env
    env = os.environ.get("PROOFML_GATE_THRESHOLD", "")
    if env.strip():
        try:
            return float(env)
        except (TypeError, ValueError):
            pass
    # 2) .proof.toml [gate].threshold
    try:
        from proofkit.config import cfg_get

        val = cfg_get(cfg, "gate", "threshold", default=None)
        if val is not None:
            return float(val)
    except Exception:
        pass
    # 3) operating_point.json
    try:
        op = _operating_point(root)
        val = op.get("threshold")
        if val is not None:
            return float(val)
    except Exception:
        pass
    # 4) default
    return _DEFAULT_THRESHOLD


def _resolve_audit_rate(cfg: dict) -> float:
    """env PROOFML_GATE_AUDIT_RATE > [gate].audit_rate > default. Clamped to [0,1]."""
    rate = _DEFAULT_AUDIT_RATE
    env = os.environ.get("PROOFML_GATE_AUDIT_RATE", "")
    resolved = False
    if env.strip():
        try:
            rate = float(env)
            resolved = True
        except (TypeError, ValueError):
            resolved = False
    if not resolved:
        try:
            from proofkit.config import cfg_get

            val = cfg_get(cfg, "gate", "audit_rate", default=None)
            if val is not None:
                rate = float(val)
        except Exception:
            rate = _DEFAULT_AUDIT_RATE
    # clamp
    if rate < 0.0:
        rate = 0.0
    elif rate > 1.0:
        rate = 1.0
    return rate


def _gate_log_path(marker_root=None) -> Path:
    """Path to gate.jsonl, creating parent dirs as needed."""
    base = _marker_base(marker_root)
    p = base / "gate.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def log_decision(entry: dict, marker_root=None) -> None:
    """Append one JSON line to gate.jsonl. Never raises (logging must not break)."""
    try:
        entry = dict(entry)
        if "ts" not in entry:
            entry["ts"] = time.time()
        with _gate_log_path(marker_root).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _project_name(root: str) -> str:
    """Best-effort project name from the root dir basename."""
    try:
        return Path(root).resolve().name
    except Exception:
        return ""


def decide(claim, transcript="", root=".", session="", marker_root=None):
    """Decide whether to skip / verify / audit a FIRST verification of a claim.

    Returns:
        None  -> gating is disabled; the caller proceeds to block as normal and
                 NOTHING is logged.
        {"decision": "skip"}   -> trust the claim; the caller skips the verifier.
        {"decision": "verify"} -> block normally (predicted risky, or fail-safe).
        {"decision": "audit"}  -> still block, but as a sampled audit of a claim
                                  predicted honest.

    Every non-None path appends a gate.jsonl decision line. NEVER raises.
    """
    try:
        if not is_enabled(root):
            return None
    except Exception:
        # If even the enabled check is unreliable, treat as disabled (no-op).
        return None

    # From here on we are committed to a gate decision and a log line. Any error
    # is fail-safe: we verify.
    try:
        cfg = _config(root)
        threshold = _resolve_threshold(cfg, root)
        audit_rate = _resolve_audit_rate(cfg)
        project = _project_name(root)
        claim_str = (claim or "")[:_CLAIM_LIMIT]

        # Predict. predict_now never raises but may return None.
        prediction = None
        try:
            from proofkit.shadow import predict_now

            prediction = predict_now(claim or "", transcript=transcript, root=root)
        except Exception:
            prediction = None

        if not isinstance(prediction, dict):
            log_decision(
                {
                    "project": project,
                    "session": session,
                    "claim": claim_str,
                    "proba": None,
                    "threshold": threshold,
                    "audit_rate": audit_rate,
                    "decision": "verify",
                    "source": None,
                    "behavior": None,
                    "reason": "predict_failed",
                },
                marker_root=marker_root,
            )
            return {"decision": "verify"}

        proba = prediction.get("proba")
        source = prediction.get("source")
        behavior = prediction.get("behavior")

        if proba is None:
            log_decision(
                {
                    "project": project,
                    "session": session,
                    "claim": claim_str,
                    "proba": None,
                    "threshold": threshold,
                    "audit_rate": audit_rate,
                    "decision": "verify",
                    "source": source,
                    "behavior": behavior,
                    "reason": "proba_none",
                },
                marker_root=marker_root,
            )
            return {"decision": "verify"}

        try:
            proba = float(proba)
        except (TypeError, ValueError):
            log_decision(
                {
                    "project": project,
                    "session": session,
                    "claim": claim_str,
                    "proba": None,
                    "threshold": threshold,
                    "audit_rate": audit_rate,
                    "decision": "verify",
                    "source": source,
                    "behavior": behavior,
                    "reason": "proba_bad",
                },
                marker_root=marker_root,
            )
            return {"decision": "verify"}

        if proba >= threshold:
            decision = "verify"
        else:
            # Predicted honest. Sample a fraction as audits; trust (skip) the rest.
            roll = random.random()
            decision = "audit" if roll < audit_rate else "skip"

        log_decision(
            {
                "project": project,
                "session": session,
                "claim": claim_str,
                "proba": proba,
                "threshold": threshold,
                "audit_rate": audit_rate,
                "decision": decision,
                "source": source,
                "behavior": behavior,
            },
            marker_root=marker_root,
        )
        return {"decision": decision}
    except Exception:
        # Absolute fail-safe: never skip on an unexpected error. Try to log, then
        # tell the caller to verify.
        try:
            log_decision(
                {
                    "project": _project_name(root),
                    "session": session,
                    "claim": (claim or "")[:_CLAIM_LIMIT],
                    "proba": None,
                    "threshold": _DEFAULT_THRESHOLD,
                    "audit_rate": _DEFAULT_AUDIT_RATE,
                    "decision": "verify",
                    "source": None,
                    "behavior": None,
                    "reason": "gate_error",
                },
                marker_root=marker_root,
            )
        except Exception:
            pass
        return {"decision": "verify"}
