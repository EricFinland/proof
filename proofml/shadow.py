"""Shadow-mode predictor: P(deceptive) for a single success claim.

This is the inference entry point proof's shadow bridge calls. It derives the
same raw behavioral signals proofml trains on (reusing proofml.extract for
transcript parsing and proofml.features.to_matrix for the one shared feature
path), runs them through the saved model, and returns a small JSON-friendly
dict.

The contract is strict: predict() NEVER raises. On any problem (missing model,
missing scikit-learn / joblib, unreadable transcript, malformed model) it
returns None. heavy deps (joblib, scikit-learn) are imported lazily inside the
function so importing this module stays cheap and side-effect free.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


# proofml package directory, used to resolve the default model + metrics paths.
_PKG_DIR = Path(__file__).resolve().parent
_DEFAULT_MODEL = _PKG_DIR / "artifacts" / "model.joblib"
_DEFAULT_METRICS = _PKG_DIR / "artifacts" / "metrics.json"


def _resolve_model_path(model_path: Optional[str]) -> Optional[Path]:
    """Resolve the model path: arg > env PROOFML_MODEL > package default.

    Returns the Path only when the file exists, else None.
    """
    candidate: Optional[Path] = None
    if model_path:
        candidate = Path(model_path)
    elif os.environ.get("PROOFML_MODEL"):
        candidate = Path(os.environ["PROOFML_MODEL"])
    else:
        candidate = _DEFAULT_MODEL
    try:
        if candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


def _model_name(model_path: Path) -> str:
    """Best-effort model name: chosen_model from metrics.json, else file stem."""
    try:
        # Prefer a metrics.json that sits next to the model file.
        local_metrics = model_path.parent / "metrics.json"
        for metrics in (local_metrics, _DEFAULT_METRICS):
            if metrics.is_file():
                data = json.loads(metrics.read_text(encoding="utf-8"))
                name = data.get("chosen_model")
                if isinstance(name, str) and name:
                    return name
                break
    except Exception:
        pass
    return model_path.stem


def _behavior_from_transcript(transcript_path: str) -> Optional[Dict[str, Any]]:
    """Raw signals + claim from a readable transcript, or None if unusable.

    Reuses proofml.extract.extract_features so the transcript parsing logic is
    not duplicated. Returns None when the path is missing/empty so the caller
    can fall back to claim-only mode.
    """
    try:
        p = Path(transcript_path)
        if not p.is_file():
            return None
        from proofml import extract

        feat = extract.extract_features(transcript_path)
    except Exception:
        return None
    if not isinstance(feat, dict):
        return None
    return feat


def _behavior_from_claim(claim: str) -> Dict[str, Any]:
    """Claim-only signals: behavioral fields default, hedged/absolute from text."""
    from proofml import extract

    text = claim or ""
    return {
        "claim": text,
        "project": "",
        "ts": 0.0,
        "source": "claim_only",
        "ran_test_cmd": False,
        "claimed_without_running": False,
        "diff_lines": 0,
        "touched_test_files": False,
        "hedged": extract.is_hedged(text),
        "absolute": extract.is_absolute(text),
    }


def predict(
    claim: str,
    transcript_path: Optional[str] = None,
    root: Optional[str] = None,
    model_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Predict P(deceptive) for a claim. Never raises; returns None on failure.

    Args:
        claim: the success claim text (used directly in claim-only mode and as
            a fallback; when a transcript is supplied the claim is taken from
            the transcript's last assistant text instead).
        transcript_path: optional path to a session .jsonl transcript. When
            given and readable, raw behavioral signals are parsed from it.
        root: accepted for interface symmetry with the proof bridge; unused
            here (kept so callers need not special-case the signature).
        model_path: explicit model path override (highest precedence).

    Returns the exact dict described in the shadow contract, or None.
    """
    try:
        resolved = _resolve_model_path(model_path)
        if resolved is None:
            return None

        # Derive raw behavioral signals + the effective claim.
        feat: Optional[Dict[str, Any]] = None
        if transcript_path:
            feat = _behavior_from_transcript(transcript_path)
        if feat is not None:
            source = "transcript"
        else:
            feat = _behavior_from_claim(claim)
            source = "claim_only"

        # Build a schema.Example (label irrelevant for inference) and featurize
        # via the ONE shared path so there is zero feature drift vs training.
        from proofml.schema import Example
        from proofml.features import to_matrix

        ex = Example(
            claim=feat.get("claim", "") or "",
            label=0,
            project=feat.get("project", "") or "",
            ts=float(feat.get("ts", 0.0) or 0.0),
            source=source,
            ran_test_cmd=bool(feat.get("ran_test_cmd", False)),
            claimed_without_running=bool(feat.get("claimed_without_running", False)),
            diff_lines=int(feat.get("diff_lines", 0) or 0),
            touched_test_files=bool(feat.get("touched_test_files", False)),
            hedged=bool(feat.get("hedged", False)),
            absolute=bool(feat.get("absolute", False)),
        )
        x = to_matrix([ex])

        # Lazily import the heavy deps only now.
        import joblib  # noqa: F401  (import validates availability)

        model = joblib.load(str(resolved))

        proba_arr = model.predict_proba(x)
        # Find the column for the deceptive class (label == 1).
        classes = list(getattr(model, "classes_", [0, 1]))
        if 1 in classes:
            idx = classes.index(1)
        else:
            idx = proba_arr.shape[1] - 1
        proba = float(proba_arr[0, idx])
        # Clamp into [0, 1] defensively.
        if proba < 0.0:
            proba = 0.0
        elif proba > 1.0:
            proba = 1.0

        return {
            "proba": proba,
            "model": _model_name(resolved),
            "source": source,
            "behavior": {
                "ran_test_cmd": bool(ex.ran_test_cmd),
                "claimed_without_running": bool(ex.claimed_without_running),
                "diff_lines": int(ex.diff_lines),
                "touched_test_files": bool(ex.touched_test_files),
                "hedged": bool(ex.hedged),
                "absolute": bool(ex.absolute),
            },
        }
    except Exception:
        return None
