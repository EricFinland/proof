import sys
from proofkit.strategies.base import (Budget, Result, run_command, split_command,
                                      verdict_for)
from proofkit.strategies.tests import verify_tests
from proofkit.verdict import Outcome, aggregate, finalize, run_claims
from proofkit.extractor import Claim

PY = sys.executable


def test_timeout_is_deferred_not_fail(tmp_path):
    r = verify_tests("tests pass", root=tmp_path,
                     command=f'"{PY}" -c "import time; time.sleep(5)"', timeout=1)
    assert r.verdict == "deferred"
    assert "TIMEOUT" in r.raw_output


def test_split_command_keeps_quoted_arg():
    assert split_command('python -c "print(1)"', windows=False) == ["python", "-c", "print(1)"]


def test_split_command_windows_backslashes():
    assert split_command(r'C:\tools\x.exe --flag "a b"', windows=True) == [r"C:\tools\x.exe", "--flag", "a b"]


def test_split_command_list_passthrough():
    assert split_command(["a", "b"]) == ["a", "b"]


def test_verdict_for():
    assert verdict_for({"code": 0, "output": "", "timed_out": False}) == "pass"
    assert verdict_for({"code": 1, "output": "", "timed_out": False}) == "fail"
    assert verdict_for({"code": 127, "output": "", "timed_out": False}) == "inconclusive"
    assert verdict_for({"code": -1, "output": "TIMEOUT", "timed_out": True}) == "deferred"


def _r(v):
    return Result("c", "m", "", "", v)


def test_aggregate_severity():
    assert aggregate([_r("pass"), _r("fail"), _r("suspect")]) == "fail"
    assert aggregate([_r("pass"), _r("suspect")]) == "suspect"
    assert aggregate([_r("pass"), _r("inconclusive")]) == "pass"
    assert aggregate([_r("deferred")]) == "inconclusive"
    assert aggregate([]) == "inconclusive"


def test_budget():
    assert Budget(None).remaining() is None
    assert not Budget(None).exhausted()
    assert Budget(0).exhausted()
    assert Budget(100).timeout(default=600) <= 100
    assert Budget(None).timeout(default=600) == 600


def test_run_claims_budget_exhausted_defers(tmp_path):
    res = run_claims([Claim("tests", "tests pass", command=f'"{PY}" -c "pass"')],
                     tmp_path, budget=Budget(0))
    assert [r.verdict for r in res] == ["deferred"]


def test_finalize_is_quiet(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("PROOF_HOME", str(tmp_path / "home"))
    out = finalize([_r("pass")], tmp_path, out_dir=tmp_path)
    assert isinstance(out, Outcome)
    assert out.overall == "pass" and out.exit_code == 0
    assert (tmp_path / "proof-report.md").exists()
    assert capsys.readouterr().out == ""


def test_outcome_unresolved():
    o = Outcome("pass", [_r("pass"), _r("deferred"), _r("inconclusive")], "")
    assert len(o.deferred) == 1 and len(o.unresolved) == 2


def test_run_command_env(tmp_path):
    res = run_command([PY, "-c", "import os; print(os.environ['PROOF_T'])"], cwd=tmp_path,
                      env={**__import__('os').environ, "PROOF_T": "yes"})
    assert "yes" in res["output"] and res["timed_out"] is False


def test_run_command_timeout_kills_grandchild_holding_stdout(tmp_path):
    import os, time
    if os.name == "nt":
        bat = tmp_path / "hold.bat"
        bat.write_text("@echo started\r\n@ping -n 30 127.0.0.1\r\n", encoding="utf-8")
        cmd = ["cmd", "/c", str(bat)]
    else:
        cmd = ["sh", "-c", "sleep 30 & sleep 30"]
    t0 = time.monotonic()
    res = run_command(cmd, cwd=tmp_path, timeout=2)
    elapsed = time.monotonic() - t0
    assert res["timed_out"] is True and res["code"] == -1
    assert "TIMEOUT after 2s" in res["output"]
    assert elapsed < 10, elapsed
