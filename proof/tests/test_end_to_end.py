import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIGGER = str(ROOT / "scripts" / "proof_trigger.py")
PROOF = str(ROOT / "scripts" / "proof.py")
FIX_FAIL = ROOT / "tests" / "fixtures" / "tests_fail"


def test_hook_fires_then_verifier_catches_the_lie(tmp_path):
    # 1) transcript with a false completion claim
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "All done, tests pass."}]}}))
    # 2) hook fires and blocks
    import os
    env = dict(os.environ, PROOF_HOME=str(tmp_path / "home"))
    hook = subprocess.run([sys.executable, TRIGGER],
        input=json.dumps({"session_id": "s", "transcript_path": str(t),
                          "stop_hook_active": False}),
        capture_output=True, text=True, env=env)
    decision = json.loads(hook.stdout)
    assert decision["decision"] == "block"
    # 3) verifier runs the real checks against the failing repo
    verify = subprocess.run([sys.executable, PROOF, "verify",
        "--transcript", str(t), "--root", str(FIX_FAIL)],
        cwd=str(tmp_path), capture_output=True, text=True)
    assert verify.returncode == 1                 # FAIL
    assert "FAIL" in verify.stdout
    report = (tmp_path / "proof-report.md").read_text(encoding="utf-8")
    assert "FAIL" in report and "pytest" in report.lower()
