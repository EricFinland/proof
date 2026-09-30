# proof/scripts/proofkit/marker.py
# v3: tracks attempts, outcomes, claim text, and pending checks per (session, claim_key),
# plus per-session meta keys (prefixed "_") for the block chain and seen-suspect hashes.
# Schema: {session: {claim_key: {"attempts": int,
#                                "last": "pass"|"fail"|"suspect"|"inconclusive"|"pending"|null,
#                                "claim": str|null, "pending": [strategy, ...]},
#                    "_chain": {"count": int, "last": str|null},
#                    "_suspect": [hash, ...]}}
# Migration: old format stored {session: [key1, key2]} (list); each becomes {"attempts": 1, "last": null}.
# v2 entries (no "claim"/"pending") are filled in lazily.
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
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
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
            p.write_text(json.dumps(migrated), encoding="utf-8")
        return migrated
    return {}


def _save(data: dict, root) -> None:
    target = _store(root)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(target)


def _entry(data, session, key):
    sess = data.setdefault(session, {})
    e = sess.get(key)
    if not isinstance(e, dict):
        e = {"attempts": 0, "last": None}
    e.setdefault("claim", None)
    e.setdefault("pending", [])
    sess[key] = e
    return e


def record_attempt(session: str, msg: str, root=None) -> None:
    """Increment the attempt counter for this (session, msg) and store the claim text."""
    data = _load(root)
    e = _entry(data, session, claim_key(msg))
    e["attempts"] = e.get("attempts", 0) + 1
    e["claim"] = msg.strip()[:4000]
    _save(data, root)


def record_outcome(session: str, msg: str, verdict: str, root=None) -> None:
    """Set the last outcome for this (session, msg). Creates entry if absent."""
    record_outcome_by_key(session, claim_key(msg), verdict, root=root)


def record_outcome_by_key(session: str, key: str, verdict: str, root=None) -> None:
    """Set the last outcome for a claim key, clear pending, and update the chain."""
    data = _load(root)
    e = _entry(data, session, key)
    e["last"] = verdict
    e["pending"] = []
    chain = data[session].setdefault("_chain", {"count": 0, "last": None})
    chain["last"] = verdict
    _save(data, root)


def get_claim(session: str, key: str, root=None):
    """Return the stored claim text for a claim key, or None."""
    e = _load(root).get(session, {}).get(key)
    return e.get("claim") if isinstance(e, dict) else None


def set_pending(session: str, msg: str, strategies, root=None) -> None:
    """Mark a claim as pending: the listed strategies did not finish inside the budget.

    Any other pending claim in the same session is demoted first, so pending_entry()
    always returns the current claim.
    """
    data = _load(root)
    key = claim_key(msg)
    for k, v in data.get(session, {}).items():
        if (k != key and not k.startswith("_") and isinstance(v, dict)
                and v.get("last") == "pending"):
            v["last"] = None
            v["pending"] = []
    e = _entry(data, session, key)
    e["last"] = "pending"
    e["pending"] = list(strategies)
    e["claim"] = msg.strip()[:4000]
    _save(data, root)


def clear_pending(session: str, root=None, key=None) -> None:
    """Demote pending claims in the session (only `key` when given): last -> None, pending -> []."""
    data = _load(root)
    changed = False
    for k, v in data.get(session, {}).items():
        if (not k.startswith("_") and isinstance(v, dict) and v.get("last") == "pending"
                and (key is None or k == key)):
            v["last"] = None
            v["pending"] = []
            changed = True
    if changed:
        _save(data, root)


def pending_entry(session: str, root=None):
    """Return (claim_key, entry) for the session's pending claim, or None."""
    for k, v in _load(root).get(session, {}).items():
        if not k.startswith("_") and isinstance(v, dict) and v.get("last") == "pending":
            return k, v
    return None


def chain_state(session: str, root=None) -> dict:
    c = _load(root).get(session, {}).get("_chain") or {}
    return {"count": int(c.get("count", 0)), "last": c.get("last")}


def chain_reset(session: str, root=None) -> None:
    data = _load(root)
    data.setdefault(session, {})["_chain"] = {"count": 0, "last": None}
    _save(data, root)


def chain_bump(session: str, root=None) -> int:
    data = _load(root)
    c = data.setdefault(session, {}).setdefault("_chain", {"count": 0, "last": None})
    c["count"] = int(c.get("count", 0)) + 1
    _save(data, root)
    return c["count"]


def suspect_seen(session: str, h: str, root=None) -> bool:
    return h in (_load(root).get(session, {}).get("_suspect") or [])


def mark_suspect_seen(session: str, h: str, root=None) -> None:
    data = _load(root)
    seen = data.setdefault(session, {}).setdefault("_suspect", [])
    if h not in seen:
        seen.append(h)
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
    - last in ("fail", "suspect", "pending") and attempts < max_cycles -> True  (fix loop)
    - attempts >= max_cycles -> False (give up, no infinite nagging)
    - last is None and attempts >= 1 and attempts < max_cycles -> True (no outcome yet)
    """
    n = attempts(session, msg, root)
    if n == 0:
        return True
    last = last_outcome(session, msg, root)
    if last == "pass":
        return False
    if last == "inconclusive":
        return False
    # fail, suspect, pending, or None (attempt recorded but no outcome yet)
    if n >= max_cycles:
        return False
    return True
