import json
from pathlib import Path

def _has(root, name): return (Path(root) / name).exists()

def detect_test_cmd(root):
    root = Path(root)
    if _has(root, "package.json"):
        pkg = json.loads((root / "package.json").read_text())
        if "test" in pkg.get("scripts", {}):
            return ["npm", "test", "--silent"]
    if _has(root, "pyproject.toml") or _has(root, "pytest.ini") or _has(root, "tests"):
        return ["python", "-m", "pytest", "-q"]
    if _has(root, "Cargo.toml"):
        return ["cargo", "test", "-q"]
    if _has(root, "go.mod"):
        return ["go", "test", "./..."]
    return None

def detect_build_cmd(root):
    root = Path(root)
    if _has(root, "package.json"):
        pkg = json.loads((root / "package.json").read_text())
        if "build" in pkg.get("scripts", {}):
            return ["npm", "run", "build"]
    if _has(root, "Cargo.toml"):
        return ["cargo", "build", "-q"]
    if _has(root, "go.mod"):
        return ["go", "build", "./..."]
    return None
