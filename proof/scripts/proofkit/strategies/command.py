from proofkit.strategies import register
from proofkit.strategies.base import (DEFAULT_COMMAND_TIMEOUT, Result, run_command,
                                      split_command, verdict_for)


@register("command")
def verify_command(claim, root, command=None, expectation=None, timeout=None):
    if not command:
        return Result(claim, "command", "", "no command given", "inconclusive", 0.2)
    res = run_command(split_command(command), cwd=root,
                      timeout=timeout or DEFAULT_COMMAND_TIMEOUT)
    return Result(claim, "command", command, res["output"][-4000:], verdict_for(res))
