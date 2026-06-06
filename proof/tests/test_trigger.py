# proof/tests/test_trigger.py
import json, subprocess, sys, os
from pathlib import Path

TRIGGER = str(Path(__file__).resolve().parents[1] / "scripts" / "proof_trigger.py")

def _run(payload, env_root):
    env = dict(os.environ, PROOF_HOME=str(env_root))
    p = subprocess.run([sys.executable, TRIGGER], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    return p

def _transcript(tmp_path, text):
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps({"type": "assistant",
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": text}]}}))
    return str(f)

def test_blocks_on_claim(tmp_path):
    tp = _transcript(tmp_path, "All done, tests pass.")
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False}, tmp_path / "home")
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    assert "verifier" in out["reason"].lower()
    assert "--root" in out["reason"]

def test_noop_on_non_claim(tmp_path):
    tp = _transcript(tmp_path, "Let me investigate the failure.")
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False}, tmp_path / "home")
    assert r.stdout.strip() == ""

def test_noop_when_stop_hook_active(tmp_path):
    tp = _transcript(tmp_path, "All done, tests pass.")
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": True}, tmp_path / "home")
    assert r.stdout.strip() == ""

def test_verifies_claim_only_once(tmp_path):
    tp = _transcript(tmp_path, "All done, tests pass.")
    home = tmp_path / "home"
    first = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False}, home)
    second = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False}, home)
    assert json.loads(first.stdout)["decision"] == "block"
    assert second.stdout.strip() == ""

def test_missing_transcript_path_is_silent(tmp_path):
    """Payload missing transcript_path must produce empty stdout and exit 0."""
    r = _run({"session_id": "s1", "stop_hook_active": False}, tmp_path / "home")
    assert r.returncode == 0
    assert r.stdout.strip() == ""

def test_transcript_path_is_directory_is_silent(tmp_path):
    """transcript_path pointing to a directory must no-op cleanly."""
    r = _run({"session_id": "s1", "transcript_path": str(tmp_path), "stop_hook_active": False}, tmp_path / "home")
    assert r.returncode == 0
    assert r.stdout.strip() == ""
