# proof/scripts/proofkit/marker.py
# v2: tracks attempt counts and outcomes per (session, claim_key).
# Schema: {session: {claim_key: {"attempts": int, "last": "pass"|"fail"|"inconclusive"|null}}}
# Migration: old format stored {session: [key1, key2]} (list); each becomes {"attempts": 1, "last": null}.
import hashlib, json
from pathlib import Path


def claim_key(message: str) -> str:
    return hashlib.sha256(message.strip().encode("utf-8")).hexdigest()[:16]


def _store(root) -> Path:
    base = Path(root) if root else Path.home() / ".proof"
    base.mkdir(parents=True, exist_ok=True)
    return base / "verified.json"


def _migrate_session(value):
    """Migrate old list-of-keys format to new dict format."""
    if isinstance(value, list):
        return {k: {"attempts": 1, "last": None} for k in value}
    if isinstance(value, dict):
        return value
    return {}


def _load(root) -> dict:
    p = _store(root)
    if p.exists():
        try:
            raw = json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
        # Migrate any sessions still in old list format
        migrated = {}
        changed = False
        for sess, val in raw.items():
            new_val = _migrate_session(val)
            migrated[sess] = new_val
            if new_val is not val:
                changed = True
        if changed:
            p.write_text(json.dumps(migrated))
        return migrated
    return {}


def _save(data: dict, root) -> None:
    _store(root).write_text(json.dumps(data))


def record_attempt(session: str, msg: str, root=None) -> None:
    """Increment the attempt counter for this (session, msg). Creates entry if absent."""
    data = _load(root)
    sess_data = data.setdefault(session, {})
    key = claim_key(msg)
    entry = sess_data.get(key, {"attempts": 0, "last": None})
    entry["attempts"] = entry.get("attempts", 0) + 1
    sess_data[key] = entry
    _save(data, root)


def record_outcome(session: str, msg: str, verdict: str, root=None) -> None:
    """Set the last outcome for this (session, msg). Creates entry if absent."""
    data = _load(root)
    sess_data = data.setdefault(session, {})
    key = claim_key(msg)
    entry = sess_data.get(key, {"attempts": 0, "last": None})
    entry["last"] = verdict
    sess_data[key] = entry
    _save(data, root)


def attempts(session: str, msg: str, root=None) -> int:
    """Return the number of recorded attempts for this (session, msg). 0 if unseen."""
    data = _load(root)
    key = claim_key(msg)
    entry = data.get(session, {}).get(key, {})
    return entry.get("attempts", 0)


def last_outcome(session: str, msg: str, root=None):
    """Return the last verdict string or None if no outcome recorded."""
    data = _load(root)
    key = claim_key(msg)
    entry = data.get(session, {}).get(key, {})
    return entry.get("last", None)


def should_block(session: str, msg: str, max_cycles: int = 3, root=None) -> bool:
    """
    Decide whether to block and demand verification.

    Policy:
    - unseen (attempts == 0) -> True  (verify at least once)
    - last == "pass"         -> False (already proven)
    - last == "inconclusive" -> False (nothing more to check automatically)
    - last == "fail" and attempts < max_cycles -> True  (fix loop)
    - attempts >= max_cycles -> False (give up, no infinite nagging)
    - last is None and attempts >= 1 and attempts < max_cycles -> True (still pending)
    """
    n = attempts(session, msg, root)
    if n == 0:
        return True
    last = last_outcome(session, msg, root)
    if last == "pass":
        return False
    if last == "inconclusive":
        return False
    # last == "fail" or last is None (attempt recorded but no outcome yet)
    if n >= max_cycles:
        return False
    return True
