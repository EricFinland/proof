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


def test_verify_pass_records_tree_fingerprint(git_repo, tmp_path, capsys):
    from proofkit import gitutil
    from proofkit.marker import claim_key, claim_tree, last_outcome, record_attempt
    from proofkit.verdict import run_verify
    home = tmp_path / "_proof_home"
    git_repo.write(".gitignore", "__pycache__/\n.pytest_cache/\nproof-report.md\n")
    git_repo.write("pyproject.toml", "[tool.pytest.ini_options]\n")
    git_repo.write("test_ok.py", "def test_ok():\n    assert 1 == 1\n")
    git_repo.commit()
    claim = "All done, tests pass."
    record_attempt("s1", claim, root=home)
    code = run_verify(root=str(git_repo.path), out_dir=str(tmp_path), session_id="s1",
                      claim_key=claim_key(claim))
    assert code == 0
    assert last_outcome("s1", claim, root=home) == "pass"
    assert claim_tree("s1", claim, root=home) == gitutil.fingerprint(git_repo.path)
