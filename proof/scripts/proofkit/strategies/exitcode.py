from proofkit.runners import detect_build_cmd
from proofkit.strategies import register
from proofkit.strategies.base import Result, run_command


def _generic(method, claim, root, cmd, default_cmd_fn=None):
    if not cmd and default_cmd_fn:
        cmd = default_cmd_fn(root)
    if isinstance(cmd, str):
        cmd = cmd.split()
    if not cmd:
        return Result(claim, method, "", f"no {method} command detected", "inconclusive", 0.3)
    res = run_command(cmd, cwd=root)
    verdict = "pass" if res["code"] == 0 else ("inconclusive" if res["code"] == 127 else "fail")
    return Result(claim, method, " ".join(cmd), res["output"][-4000:], verdict)


@register("build")
def verify_build(claim, root, command=None, expectation=None):
    return _generic("build", claim, root, command, detect_build_cmd)


@register("typecheck")
def verify_typecheck(claim, root, command=None, expectation=None):
    return _generic("typecheck", claim, root, command)


@register("lint")
def verify_lint(claim, root, command=None, expectation=None):
    return _generic("lint", claim, root, command)
