from proofkit.runners import detect_build_cmd
from proofkit.strategies import register
from proofkit.strategies.base import (DEFAULT_COMMAND_TIMEOUT, Result, run_command,
                                      split_command, verdict_for)


def _generic(method, claim, root, cmd, default_cmd_fn=None, timeout=None):
    if not cmd and default_cmd_fn:
        cmd = default_cmd_fn(root)
    cmd = split_command(cmd)
    if not cmd:
        return Result(claim, method, "", f"no {method} command detected", "inconclusive", 0.3)
    res = run_command(cmd, cwd=root, timeout=timeout or DEFAULT_COMMAND_TIMEOUT)
    return Result(claim, method, " ".join(cmd), res["output"][-4000:], verdict_for(res))


@register("build")
def verify_build(claim, root, command=None, expectation=None, timeout=None):
    return _generic("build", claim, root, command, detect_build_cmd, timeout)


@register("typecheck")
def verify_typecheck(claim, root, command=None, expectation=None, timeout=None):
    return _generic("typecheck", claim, root, command, timeout=timeout)


@register("lint")
def verify_lint(claim, root, command=None, expectation=None, timeout=None):
    return _generic("lint", claim, root, command, timeout=timeout)
