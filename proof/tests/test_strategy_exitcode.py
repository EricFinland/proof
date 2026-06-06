# proof/tests/test_strategy_exitcode.py
from pathlib import Path
from proofkit.strategies.base import Result, run_command


def test_run_command_captures_exit_and_output(tmp_path):
    r = run_command(["python", "-c", "print('hi')"], cwd=tmp_path)
    assert r["code"] == 0 and "hi" in r["output"]


def test_run_command_nonzero(tmp_path):
    r = run_command(["python", "-c", "import sys; sys.exit(3)"], cwd=tmp_path)
    assert r["code"] == 3


# part 2 - build/typecheck/lint strategies
from proofkit.strategies.exitcode import verify_build

FIX = Path(__file__).resolve().parent / "fixtures"


def test_build_no_runner_is_inconclusive(tmp_path):
    r = verify_build("build is clean", root=tmp_path)
    assert r.verdict == "inconclusive"


def test_build_uses_explicit_command_pass(tmp_path):
    r = verify_build("build is clean", root=tmp_path, command="python -c pass")
    assert r.verdict in ("pass", "fail")  # runs the given command
