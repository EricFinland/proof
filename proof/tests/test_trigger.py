# proof/tests/test_trigger.py
# Migrated for trigger v3: the hook runs checks inline, so every run passes an
# explicit cwd (an empty tmp dir or a fixture copy). Without one the hook would
# run pytest on this repo from inside the test suite.
import json, os, shutil, subprocess, sys
from pathlib import Path

TRIGGER = str(Path(__file__).resolve().parents[1] / "scripts" / "proof_trigger.py")
FIX = Path(__file__).resolve().parent / "fixtures"


def _empty(tmp_path):
    d = tmp_path / "empty"
    d.mkdir(exist_ok=True)
    return d


def _run(payload, env_root, cwd):
    env = dict(os.environ, PROOF_HOME=str(env_root))
    p = subprocess.run(
        [sys.executable, TRIGGER],
        input=json.dumps(payload),
        capture_output=True, text=True, env=env,
        cwd=str(cwd),
    )
    return p


def _transcript(tmp_path, text):
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps({
        "type": "assistant",
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": text}]},
    }), encoding="utf-8")
    return str(f)


# 1) fresh claim, nothing runnable inline -> block with the deferral directive
def test_fresh_claim_blocks_with_session(tmp_path):
    tp = _transcript(tmp_path, "All done, tests pass.")
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False},
             tmp_path / "home", cwd=_empty(tmp_path))
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    assert "--session" in out["reason"]
    assert "verifier" in out["reason"].lower()
    assert "--root" in out["reason"]
    assert "--claim-key" in out["reason"]


# 2) after pass outcome recorded -> same claim -> silent
def test_silent_after_pass(tmp_path):
    from proofkit.marker import record_attempt, record_outcome
    msg = "All done, tests pass."
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    tp = _transcript(tmp_path, msg)
    record_attempt("s1", msg, root=home)
    record_outcome("s1", msg, "pass", root=home)
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False}, home,
             cwd=_empty(tmp_path))
    assert r.stdout.strip() == ""


# 3) prior fail -> same claim -> blocks again with the fresh FAIL receipt and attempt count
def test_reblock_after_fail_with_receipts(tmp_path):
    from proofkit.marker import chain_bump, record_attempt, record_outcome
    msg = "All done, tests pass."
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    cwd = tmp_path / "work"
    shutil.copytree(FIX / "tests_fail", cwd)
    tp = _transcript(tmp_path, msg)
    # simulate 1 prior blocked attempt + fail outcome in the current block chain;
    # the re-claim arrives inside that chain (stop_hook_active set by the harness)
    record_attempt("s1", msg, root=home)
    chain_bump("s1", root=home)
    record_outcome("s1", msg, "fail", root=home)
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": True},
             home, cwd=cwd)
    out = json.loads(r.stdout)
    assert out["decision"] == "block"
    reason = out["reason"]
    assert "FAIL tests" in reason
    assert "assert 1 == 2" in reason
    assert "attempt 2 of 3" in reason.lower()


# 4) 3 attempts + fail -> silent (gave up)
def test_silent_after_max_cycles(tmp_path):
    from proofkit.marker import record_attempt, record_outcome
    msg = "All done, tests pass."
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    tp = _transcript(tmp_path, msg)
    for _ in range(3):
        record_attempt("s1", msg, root=home)
    record_outcome("s1", msg, "fail", root=home)
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False}, home,
             cwd=_empty(tmp_path))
    assert r.stdout.strip() == ""


# 5) stop_hook_active True with no pending claim and no failing chain -> silent.
# (v3 keeps going inside a chain only for pending verification or the fix loop.)
def test_noop_when_stop_hook_active(tmp_path):
    tp = _transcript(tmp_path, "All done, tests pass.")
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": True},
             tmp_path / "home", cwd=_empty(tmp_path))
    assert r.stdout.strip() == ""


# 6) non-claim -> silent (unchanged)
def test_noop_on_non_claim(tmp_path):
    tp = _transcript(tmp_path, "Let me investigate the failure.")
    r = _run({"session_id": "s1", "transcript_path": tp, "stop_hook_active": False},
             tmp_path / "home", cwd=_empty(tmp_path))
    assert r.stdout.strip() == ""


# crash-safety: missing transcript_path -> silent exit 0
def test_missing_transcript_path_is_silent(tmp_path):
    r = _run({"session_id": "s1", "stop_hook_active": False}, tmp_path / "home",
             cwd=_empty(tmp_path))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


# crash-safety: transcript_path pointing to a directory -> silent exit 0
def test_transcript_path_is_directory_is_silent(tmp_path):
    r = _run({"session_id": "s1", "transcript_path": str(tmp_path), "stop_hook_active": False},
             tmp_path / "home", cwd=_empty(tmp_path))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_trigger_import_error_prints_nothing(tmp_path):
    scripts = tmp_path / "scripts"
    (scripts / "proofkit").mkdir(parents=True)
    shutil.copy(TRIGGER, scripts / "proof_trigger.py")
    (scripts / "proofkit" / "__init__.py").write_text("", encoding="utf-8")
    (scripts / "proofkit" / "hookflow.py").write_text("raise ImportError('broken install')\n",
                                                     encoding="utf-8")
    p = subprocess.run([sys.executable, str(scripts / "proof_trigger.py")],
                       input=json.dumps({"session_id": "s", "transcript_path": ""}),
                       capture_output=True, text=True, cwd=str(tmp_path),
                       env=dict(os.environ, PROOF_HOME=str(tmp_path / "home")))
    assert p.returncode == 0 and p.stdout == "" and p.stderr == "", (p.stdout, p.stderr)


def test_trigger_swallows_stderr_noise(tmp_path, monkeypatch, capsys):
    import io
    sys.path.insert(0, str(Path(TRIGGER).parent))
    import proof_trigger

    def noisy(payload, cwd, marker_root=None):
        print("noise on stdout")
        print("noise on stderr", file=sys.stderr)
        return {"systemMessage": "ok"}

    monkeypatch.setattr(proof_trigger, "decide_stop", noisy)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "s"})))
    monkeypatch.chdir(tmp_path)
    proof_trigger.main()
    out = capsys.readouterr()
    assert json.loads(out.out) == {"systemMessage": "ok"} and out.err == "", out
