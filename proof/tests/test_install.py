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


def _stop_entries(settings):
    return json.loads(settings.read_text())["hooks"].get("Stop", [])


def test_stop_hook_has_default_timeout(tmp_path, monkeypatch):
    monkeypatch.delenv("PROOF_INLINE_BUDGET", raising=False)
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    arm(settings, "/abs/proof_trigger.py", session_start_path="/abs/proof_session_start.py")
    ours = [h for e in _stop_entries(settings) for h in e["hooks"]]
    assert [h["timeout"] for h in ours] == [120]


def test_stop_timeout_follows_inline_budget(tmp_path, monkeypatch):
    monkeypatch.delenv("PROOF_INLINE_BUDGET", raising=False)
    (tmp_path / ".proof.toml").write_text("[verify]\ninline_budget = 200\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    arm(settings, "/abs/proof_trigger.py", session_start_path="/abs/proof_session_start.py")
    assert _stop_entries(settings)[0]["hooks"][0]["timeout"] == 230


def test_rearm_leaves_single_entries_and_upgrades_v2(tmp_path, monkeypatch):
    monkeypatch.delenv("PROOF_INLINE_BUDGET", raising=False)
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": '"py" "/old/proof_trigger.py"'}]}]}}))
    for _ in range(2):
        arm(settings, "/abs/proof_trigger.py", session_start_path="/abs/proof_session_start.py")
    data = json.loads(settings.read_text())
    assert len(data["hooks"]["Stop"]) == 1
    assert data["hooks"]["Stop"][0]["hooks"][0]["timeout"] == 120
    assert "/old/" not in json.dumps(data)
    ss = data["hooks"]["SessionStart"]
    assert len(ss) == 1 and ss[0]["hooks"][0]["timeout"] == 30
    assert "proof_session_start.py" in ss[0]["hooks"][0]["command"]


def test_disarm_removes_both_hooks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    arm(settings, "/abs/proof_trigger.py", session_start_path="/abs/proof_session_start.py")
    disarm(settings)
    data = json.loads(settings.read_text())
    assert data["hooks"]["Stop"] == [] and data["hooks"]["SessionStart"] == []
    assert is_armed(settings) is False


def test_arm_without_session_start_path_leaves_session_start_alone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    arm(settings, "/abs/proof_trigger.py")
    assert "SessionStart" not in json.loads(settings.read_text())["hooks"]


V2_HINT = 'armed (v2 hook entry: run "proof arm" again to upgrade)'


def _status(settings, capsys):
    sys.path.insert(0, str(Path(PROOF).parent))
    import proof as proof_cli
    code = proof_cli.main(["status", "--settings", str(settings)])
    return code, capsys.readouterr().out.strip()


def test_status_flags_v2_stop_entry_without_timeout(tmp_path, capsys):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": '"python" "/abs/proof_trigger.py"'}]}]}}), encoding="utf-8")
    assert _status(settings, capsys) == (0, V2_HINT)


def test_status_flags_missing_session_start(tmp_path, capsys):
    settings = tmp_path / ".claude" / "settings.json"
    arm(settings, "/abs/proof_trigger.py", timeout=120)
    assert _status(settings, capsys) == (0, V2_HINT)


def test_status_after_v3_arm_is_plain_armed(tmp_path, capsys):
    settings = tmp_path / ".claude" / "settings.json"
    arm(settings, "/abs/proof_trigger.py", session_start_path="/abs/proof_session_start.py",
        timeout=120)
    assert _status(settings, capsys) == (0, "armed")
    disarm(settings)
    assert _status(settings, capsys) == (0, "disarmed")
