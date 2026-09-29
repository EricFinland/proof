from proofkit.runners import detect_test_cmd
from proofkit.strategies import register
from proofkit.strategies.base import (DEFAULT_COMMAND_TIMEOUT, Result, run_command,
                                      split_command, verdict_for)


@register("tests")
def verify_tests(claim, root, command=None, expectation=None, timeout=None):
    cmd = split_command(command) if command else detect_test_cmd(root)
    if not cmd:
        return Result(claim, "tests", "", "no test runner detected", "inconclusive", 0.3)
    res = run_command(cmd, cwd=root, timeout=timeout or DEFAULT_COMMAND_TIMEOUT)
    return Result(claim, "tests", " ".join(cmd), res["output"][-4000:], verdict_for(res))
