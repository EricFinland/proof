from proofkit.runners import detect_test_cmd
from proofkit.strategies import register
from proofkit.strategies.base import Result, run_command


@register("tests")
def verify_tests(claim, root, command=None, expectation=None):
    cmd = command.split() if command else detect_test_cmd(root)
    if not cmd:
        return Result(claim, "tests", "", "no test runner detected", "inconclusive", 0.3)
    res = run_command(cmd, cwd=root)
    verdict = "pass" if res["code"] == 0 else ("inconclusive" if res["code"] == 127 else "fail")
    return Result(claim, "tests", " ".join(cmd), res["output"][-4000:], verdict)
