# proof/tests/test_install.py
import json
from proofkit.install import arm, disarm, is_armed

def test_arm_adds_stop_hook(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    arm(settings_path=settings, trigger_path="/abs/proof_trigger.py")
    data = json.loads(settings.read_text())
    hooks = data["hooks"]["Stop"]
    cmds = json.dumps(hooks)
    assert "proof_trigger.py" in cmds
    assert is_armed(settings_path=settings) is True

def test_disarm_removes_only_proof_hook(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": "other.py"}]}
    ]}}))
    arm(settings_path=settings, trigger_path="/abs/proof_trigger.py")
    disarm(settings_path=settings)
    data = json.loads(settings.read_text())
    cmds = json.dumps(data.get("hooks", {}).get("Stop", []))
    assert "proof_trigger.py" not in cmds
    assert "other.py" in cmds  # preserved
    assert is_armed(settings_path=settings) is False


import subprocess, sys
from pathlib import Path
PROOF = str(Path(__file__).resolve().parents[1] / "scripts" / "proof.py")

def test_cli_arm_status_disarm_roundtrip(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    def run(*a): return subprocess.run([sys.executable, PROOF, *a],
        capture_output=True, text=True)
    run("arm", "--settings", str(settings))
    assert "armed" in run("status", "--settings", str(settings)).stdout
    run("disarm", "--settings", str(settings))
    assert "disarmed" in run("status", "--settings", str(settings)).stdout
