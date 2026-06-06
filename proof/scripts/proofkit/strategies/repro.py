import shlex
from proofkit.strategies import register
from proofkit.strategies.base import Result, run_command


@register("repro")
def verify_repro(claim, root, command=None, expectation=None):
    if not command:
        return Result(claim, "repro", "", "no repro command", "inconclusive", 0.2)
    res = run_command(shlex.split(command, posix=False), cwd=root)
    verdict = "pass" if res["code"] == 0 else "fail"
    return Result(claim, "repro", command, res["output"][-4000:], verdict)
