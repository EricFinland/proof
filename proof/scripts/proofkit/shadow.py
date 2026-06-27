"""Shadow-mode bridge from proof to the proofml research layer.

This module is the ONLY place proof reaches into proofml, and it does so lazily
and defensively. It imports stdlib only at module import time so proofkit stays
zero-dependency. proofml (and its scikit-learn / joblib stack) is imported only
when shadow mode is explicitly enabled and only inside the function body.

Shadow mode is OFF by default. When OFF, maybe_predict returns None immediately
and proofml is never imported, so proof behaves exactly as it always has.

Trigger (either one enables it):
  - env var PROOFML_SHADOW truthy ("1" / "true" / "yes", case-insensitive)
  - .proof.toml has a [shadow] table with enabled = true
"""
import os
import sys


_TRUTHY = {"1", "true", "yes"}


def _env_enabled() -> bool:
    """True if PROOFML_SHADOW is set to a truthy value."""
    val = os.environ.get("PROOFML_SHADOW", "")
    return val.strip().lower() in _TRUTHY


def _config_enabled(root: str) -> bool:
    """True if .proof.toml [shadow] enabled = true. Never raises."""
    try:
        from proofkit.config import load_config, cfg_get

        cfg = load_config(root)
        return cfg_get(cfg, "shadow", "enabled", default=False) is True
    except Exception:
        return False


def is_enabled(root: str = ".") -> bool:
    """Whether shadow mode is enabled via env var or .proof.toml. Never raises."""
    try:
        return _env_enabled() or _config_enabled(root)
    except Exception:
        return False


def _import_shadow():
    """Import proofml.shadow, retrying with PROOFML_PATH on sys.path. May return None."""
    try:
        import proofml.shadow as _shadow
        return _shadow
    except ImportError:
        extra = os.environ.get("PROOFML_PATH", "")
        if extra:
            try:
                if extra not in sys.path:
                    sys.path.insert(0, extra)
                import proofml.shadow as _shadow
                return _shadow
            except ImportError:
                return None
        return None


def maybe_predict(claim: str, transcript: str = "", root: str = "."):
    """Run a shadow prediction iff shadow mode is enabled. Never raises.

    Returns the proofml.shadow.predict dict, or None when shadow mode is off,
    proofml is unavailable, or anything goes wrong. The caller treats a None
    result as "no shadow data" and leaves the ledger entry untouched.
    """
    try:
        if not is_enabled(root):
            return None
        shadow = _import_shadow()
        if shadow is None:
            return None
        result = shadow.predict(claim, transcript_path=transcript or None, root=root)
        if isinstance(result, dict):
            return result
        return None
    except Exception:
        return None
