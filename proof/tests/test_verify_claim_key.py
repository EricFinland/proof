import json, os, shutil, subprocess, sys
from pathlib import Path

PROOF = str(Path(__file__).resolve().parents[1] / "scripts" / "proof.py")
FIX = Path(__file__).resolve().parent / "fixtures" / "tests_fail"


def test_verify_uses_stored_claim_not_latest_message(tmp_path):
    from proofkit.marker import record_attempt, claim_key, last_outcome
    home = tmp_path / "home"; home.mkdir()
    work = tmp_path / "work"; shutil.copytree(FIX, work)
    claim = "All done, tests pass."
    record_attempt("s1", claim, root=home)
    tp = tmp_path / "t.jsonl"
    tp.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "I'll spawn a verifier now."}]}}), encoding="utf-8")
    env = dict(os.environ, PROOF_HOME=str(home))
    p = subprocess.run([sys.executable, PROOF, "verify", "--transcript", str(tp),
                        "--root", str(work), "--session", "s1",
                        "--claim-key", claim_key(claim), "--out-dir", str(tmp_path)],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 1, p.stdout + p.stderr
    assert last_outcome("s1", claim, root=home) == "fail"
