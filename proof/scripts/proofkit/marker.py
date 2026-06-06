# proof/scripts/proofkit/marker.py
import hashlib, json
from pathlib import Path

def claim_key(message: str) -> str:
    return hashlib.sha256(message.strip().encode("utf-8")).hexdigest()[:16]

def _store(root) -> Path:
    base = Path(root) if root else Path.home() / ".proof"
    base.mkdir(parents=True, exist_ok=True)
    return base / "verified.json"

def _load(root) -> dict:
    p = _store(root)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}

def already_verified(session_id: str, message: str, root=None) -> bool:
    data = _load(root)
    return claim_key(message) in data.get(session_id, [])

def mark_verified(session_id: str, message: str, root=None) -> None:
    p = _store(root)
    data = _load(root)
    keys = set(data.get(session_id, []))
    keys.add(claim_key(message))
    data[session_id] = sorted(keys)
    p.write_text(json.dumps(data))
