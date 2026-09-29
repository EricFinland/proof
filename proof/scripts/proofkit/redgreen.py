"""Prove a fix: the repro must fail on the session baseline and pass now.

Safety rules for the temporary baseline worktree:
- It lives in a fresh directory under $PROOF_HOME/work that this module creates.
- Test files are copied in before the dependency link is made, and never
  through a link that points outside the worktree.
- Cleanup removes the dependency link first. The worktree is deleted only once
  every link is confirmed gone, so a failed unlink can never delete through a
  junction or symlink into the real node_modules. Leaking a temp directory is
  preferred over that.
- Only this worktree's own registration is removed. No global prune.
"""
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from proofkit import gitutil
from proofkit.config import cfg_get
from proofkit.findings import Finding, suspect_result
from proofkit.runners import detect_test_cmd
from proofkit.strategies.base import Budget, Result, run_command, split_command
from proofkit.tamper import is_test_path

MIN_BUDGET = 10.0
_REPRO_LINE = re.compile(r"^\s*Repro:\s*`([^`]+)`", re.M | re.I)
_TEST_FILE = re.compile(r"(^|/)test_[^/]*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$|_test\.go$")
_ENV_FAILURE = re.compile(
    r"command not found|No module named|Cannot find module|is not recognized as an internal"
    r"|ENOENT|no tests ran|collected 0 items|error: no such command", re.I)
_NO_REPRO = "no repro found; add a test or a Repro: line"


@dataclass
class ReproSpec:
    command: list
    source: str
    copy_files: list = field(default_factory=list)


def _targeted(root, cfg, targets):
    base = cfg_get(cfg, "commands", "test") or cfg_get(cfg, "commands", "tests")
    cmd = split_command(base) if base else (detect_test_cmd(root) or [])
    if not cmd:
        return None
    joined = " ".join(cmd)
    if "pytest" in joined:
        py = [t for t in targets if t.endswith(".py")]
        return cmd + py if py else None
    if cmd[:2] == ["go", "test"]:
        pkgs = sorted({"./" + str(PurePosixPath(t).parent) for t in targets if t.endswith("_test.go")})
        return ["go", "test"] + pkgs if pkgs else None
    js = [t for t in targets if re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", t)]
    if not js:
        return None
    if cmd[0] == "npm":
        return cmd + ["--"] + js
    if cmd[0] in ("pnpm", "yarn", "bun") or "vitest" in joined or "jest" in joined:
        return cmd + js
    return None


def find_repro(msg, changes, root, cfg):
    base_root = (changes.root if changes is not None else "") or root
    files = changes.files if changes is not None else []
    copy = [f.path for f in files if f.status in ("A", "M") and is_test_path(f.path)]
    targets = [p for p in copy if _TEST_FILE.search(p)]
    if targets:
        cmd = _targeted(base_root, cfg, targets)
        if cmd:
            return ReproSpec(cmd, "tests", copy)
    configured = cfg_get(cfg, "repro", "command", default="")
    if configured:
        return ReproSpec(split_command(configured), "config", copy)
    m = _REPRO_LINE.search(msg or "")
    if m:
        return ReproSpec(split_command(m.group(1)), "claim", copy)
    return None


def _home(marker_root):
    if marker_root:
        return Path(marker_root)
    env = os.environ.get("PROOF_HOME", "")
    return Path(env) if env else Path.home() / ".proof"


def _make_link(src, dst):
    """Directory link dst -> src: a junction on Windows (no admin needed), a symlink elsewhere."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(src), str(dst))
        else:
            os.symlink(src, dst, target_is_directory=True)
    except (OSError, AttributeError, ImportError):
        pass
    return os.path.lexists(dst)


def _is_link(path):
    """Symlink or Windows reparse point (junction), without following it."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return os.path.islink(path) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _link_deps(root, wt):
    src, dst = Path(root) / "node_modules", Path(wt) / "node_modules"
    if not src.is_dir() or os.path.lexists(dst):
        return []
    # dst did not exist before, so anything there now (even from a failed attempt)
    # is ours and must be unlinked before the worktree is deleted.
    _make_link(src, dst)
    return [dst] if os.path.lexists(dst) else []


def _unlink(link):
    # Removes only the link. On Windows os.rmdir removes a junction without
    # touching its target, and refuses a real non-empty directory.
    try:
        if os.name == "nt":
            os.rmdir(link)
        else:
            os.unlink(link)
    except OSError:
        pass


def _contained(wt, dest):
    """True when writing `dest` stays inside the worktree after following links."""
    try:
        return Path(dest).resolve().is_relative_to(Path(wt).resolve())
    except (OSError, ValueError, RuntimeError):
        return False


def _copy_tests(root, wt, rels):
    for rel in rels:
        src, dest = Path(root) / rel, Path(wt) / rel
        if not src.is_file() or not _contained(wt, dest):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if _contained(wt, dest):
            shutil.copy2(src, dest)


def _py_env(tree):
    env = dict(os.environ)
    parts = [str(tree)] + ([str(Path(tree) / "src")] if (Path(tree) / "src").is_dir() else [])
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _env_failure(res):
    return res["code"] == 127 or bool(_ENV_FAILURE.search(res["output"][-4000:]))


def _judge(claim, spec, cmd, red, green):
    if green["code"] != 0:
        return Result(claim, "redgreen", cmd, "current tree: repro fails\n" + green["output"][-3000:], "fail")
    if red["code"] != 0 and _env_failure(red):
        return Result(claim, "redgreen", cmd, "baseline could not run the repro (environment):\n"
                      + red["output"][-2000:], "inconclusive", 0.3)
    if red["code"] != 0:
        return Result(claim, "redgreen", cmd, "fix proven: repro failed before the change and passes now\n"
                      + "baseline output:\n" + red["output"][-1500:], "pass")
    f = Finding("repro-already-green", spec.copy_files[0] if spec.copy_files else "", 0,
                "repro passes on the baseline without your change, so it does not prove the fix")
    return suspect_result(claim, "redgreen", "fix not proven", [f], command=cmd)


def _cleanup(root, wt, links):
    """Remove the worktree. Returns False when it was left in place on purpose."""
    links = list(links)
    deps = Path(wt) / "node_modules"
    if deps not in links and _is_link(deps):
        links.append(deps)  # defense in depth: a link we lost track of is still a link
    for link in links:
        _unlink(link)
    if any(os.path.lexists(link) for link in links):
        return False
    removed = True
    try:
        gitutil.git(root, "worktree", "remove", "--force", str(wt))
    except gitutil.GitError:
        removed = False
    shutil.rmtree(wt, ignore_errors=True)
    if not removed:
        # The directory is gone now, so this drops only our own registration.
        try:
            gitutil.git(root, "worktree", "remove", "--force", str(wt))
        except gitutil.GitError:
            pass
    return True


def run(claim, spec, root, base_commit, budget=None, marker_root=None):
    budget = budget or Budget(None)
    if spec is None:
        return Result(claim, "redgreen", "", _NO_REPRO, "inconclusive", 0.0)
    cmd = " ".join(spec.command)
    rem = budget.remaining()
    if rem is not None and rem < MIN_BUDGET:
        return Result(claim, "redgreen", cmd, "deferred: not enough inline budget", "deferred", 0.0)
    wt, links = None, []
    try:
        work = _home(marker_root) / "work"
        work.mkdir(parents=True, exist_ok=True)
        # A fresh empty directory we own, so cleanup can never hit anything else.
        wt = Path(tempfile.mkdtemp(prefix="wt-", dir=str(work)))
        nohooks = str(work / ".no-hooks")
        gitutil.git(root, "-c", f"core.hooksPath={nohooks}", "worktree", "add", "--detach",
                    str(wt), base_commit, timeout=budget.timeout())
        _copy_tests(root, wt, spec.copy_files)   # before linking: never copy through the link
        links = _link_deps(root, wt)
        red = run_command(spec.command, cwd=wt, timeout=budget.timeout(), env=_py_env(wt))
        if red.get("timed_out"):
            return Result(claim, "redgreen", cmd, "deferred: baseline run timed out", "deferred", 0.0)
        green = run_command(spec.command, cwd=root, timeout=budget.timeout(), env=_py_env(root))
        if green.get("timed_out"):
            return Result(claim, "redgreen", cmd, "deferred: current run timed out", "deferred", 0.0)
        return _judge(claim, spec, cmd, red, green)
    except gitutil.GitError as e:
        return Result(claim, "redgreen", cmd, f"could not create baseline worktree: {e}", "inconclusive", 0.2)
    except OSError as e:
        return Result(claim, "redgreen", cmd, f"could not prepare baseline worktree: {e}", "inconclusive", 0.2)
    finally:
        if wt is not None:
            try:
                _cleanup(root, wt, links)
            except Exception:
                pass
