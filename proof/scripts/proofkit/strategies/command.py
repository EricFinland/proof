import shlex
from proofkit.strategies import register
from proofkit.strategies.base import Result, run_command


@register("command")
def verify_command(claim, root, command=None, expectation=None):
    if not command:
        return Result(claim, "command", "", "no command given", "inconclusive", 0.2)
    cmd = shlex.split(command, posix=False)
    res = run_command(cmd, cwd=root)
    verdict = "pass" if res["code"] == 0 else ("inconclusive" if res["code"] == 127 else "fail")
    return Result(claim, "command", command, res["output"][-4000:], verdict)
