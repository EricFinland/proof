# proof/scripts/proofkit/install.py
import json, sys
from pathlib import Path

MARK = "proof_trigger.py"
SESSION_MARK = "proof_session_start.py"
SESSION_START_TIMEOUT = 30


def _load(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _entry(path: str, timeout) -> dict:
    return {"hooks": [{"type": "command", "command": f'"{sys.executable}" "{path}"',
                       "timeout": int(timeout)}]}


def stop_timeout(project_root=".") -> int:
    from proofkit.config import load_config
    from proofkit.hookflow import budget_seconds
    return int(budget_seconds(load_config(str(project_root)))) + 30


def _replace(hooks: dict, event: str, mark: str, entry: dict) -> None:
    kept = [h for h in hooks.get(event, []) if mark not in json.dumps(h)]
    kept.append(entry)
    hooks[event] = kept


def arm(settings_path: Path, trigger_path: str, session_start_path=None, timeout=None) -> None:
    settings_path = Path(settings_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load(settings_path)
    hooks = data.setdefault("hooks", {})
    if timeout is None:
        timeout = stop_timeout(".")
    _replace(hooks, "Stop", MARK, _entry(trigger_path, timeout))
    if session_start_path:
        _replace(hooks, "SessionStart", SESSION_MARK,
                 _entry(session_start_path, SESSION_START_TIMEOUT))
    _write(settings_path, data)


def disarm(settings_path: Path) -> None:
    settings_path = Path(settings_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load(settings_path)
    hooks = data.setdefault("hooks", {})
    for event, mark in (("Stop", MARK), ("SessionStart", SESSION_MARK)):
        hooks[event] = [h for h in hooks.get(event, []) if mark not in json.dumps(h)]
    _write(settings_path, data)


def is_armed(settings_path: Path) -> bool:
    data = _load(Path(settings_path))
    return any(MARK in json.dumps(h) for h in data.get("hooks", {}).get("Stop", []))
