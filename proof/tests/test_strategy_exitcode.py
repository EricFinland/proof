# proof/tests/test_strategy_exitcode.py  (part 1)
from proofkit.strategies.base import Result, run_command


def test_run_command_captures_exit_and_output(tmp_path):
    r = run_command(["python", "-c", "print('hi')"], cwd=tmp_path)
    assert r["code"] == 0 and "hi" in r["output"]


def test_run_command_nonzero(tmp_path):
    r = run_command(["python", "-c", "import sys; sys.exit(3)"], cwd=tmp_path)
    assert r["code"] == 3
