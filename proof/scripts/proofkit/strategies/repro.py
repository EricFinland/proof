from proofkit.strategies import register
from proofkit.strategies.base import (DEFAULT_COMMAND_TIMEOUT, Result, run_command,
                                      split_command, verdict_for)


@register("repro")
def verify_repro(claim, root, command=None, expectation=None, timeout=None):
    if not command:
        return Result(claim, "repro", "", "no repro command", "inconclusive", 0.2)
    res = run_command(split_command(command), cwd=root,
                      timeout=timeout or DEFAULT_COMMAND_TIMEOUT)
    return Result(claim, "repro", command, res["output"][-4000:], verdict_for(res))
