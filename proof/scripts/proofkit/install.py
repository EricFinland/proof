# proof/scripts/proofkit/install.py
import json, sys
from pathlib import Path

MARK = "proof_trigger.py"

def _load(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}

def _entry(trigger_path: str) -> dict:
    cmd = f'{json.dumps(sys.executable)} {json.dumps(trigger_path)}'.replace('"', '')
    return {"hooks": [{"type": "command", "command": f'python "{trigger_path}"'}]}

def arm(settings_path: Path, trigger_path: str) -> None:
    settings_path = Path(settings_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load(settings_path)
    hooks = data.setdefault("hooks", {})
    stop = hooks.setdefault("Stop", [])
    if not any(MARK in json.dumps(h) for h in stop):
        stop.append(_entry(trigger_path))
    settings_path.write_text(json.dumps(data, indent=2))

def disarm(settings_path: Path) -> None:
    settings_path = Path(settings_path)
    data = _load(settings_path)
    stop = data.get("hooks", {}).get("Stop", [])
    data.setdefault("hooks", {})["Stop"] = [h for h in stop if MARK not in json.dumps(h)]
    settings_path.write_text(json.dumps(data, indent=2))

def is_armed(settings_path: Path) -> bool:
    data = _load(Path(settings_path))
    return any(MARK in json.dumps(h) for h in data.get("hooks", {}).get("Stop", []))
