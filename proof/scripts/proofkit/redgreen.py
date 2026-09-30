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
_JS_UNCLEAN = re.compile(r"Test suite failed to run|Failed to load|Failed to resolve import"
                         r"|Cannot find module|SyntaxError")
_GO_UNCLEAN = re.compile(r"\[build failed\]|\[setup failed\]|undefined:")
_NO_REPRO = "no repro found; add a test or a Repro: line"


@dataclass
class ReproSpec:
    command: list
    source: str
    copy_files: list = field(default_factory=list)  # toplevel-relative
    cwd: str = ""  # project root relative to the git toplevel, forward slashes, "" at top level


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


def _project_cwd(root, top):
    """`root` relative to the git toplevel `top`, forward slashes, "" at top level."""
    try:
        rel = Path(root).resolve().relative_to(Path(top).resolve()).as_posix()
    except (OSError, ValueError, RuntimeError):
        return ""
    return "" if rel == "." else rel


def _toplevel(root):
    try:
        return gitutil.toplevel(root)
    except gitutil.GitError:
        return Path(root)


def find_repro(msg, changes, root, cfg):
    top = (changes.root if changes is not None else "") or _toplevel(root)
    cwd = _project_cwd(root, top)
    files = changes.files if changes is not None else []
    # Toplevel-relative: what gets copied into the baseline worktree.
    copy = [f.path for f in files if f.status in ("A", "M") and is_test_path(f.path)]
    # Targets are relative to the project root; test files outside it are dropped.
    prefix = cwd + "/" if cwd else ""
    targets = [p[len(prefix):] for p in copy if _TEST_FILE.search(p) and p.startswith(prefix)]
    if targets:
        cmd = _targeted(root, cfg, targets)
        if cmd:
            return ReproSpec(cmd, "tests", copy, cwd)
    configured = cfg_get(cfg, "repro", "command", default="")
    if configured:
        return ReproSpec(split_command(configured), "config", copy, cwd)
    m = _REPRO_LINE.search(msg or "")
    if m:
        return ReproSpec(split_command(m.group(1)), "claim", copy, cwd)
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


def _link_deps(project, wt_project):
    """Link project/node_modules into the same project directory of the worktree."""
    src, dst = Path(project) / "node_modules", Path(wt_project) / "node_modules"
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


def _prog(arg):
    """Lowercased program name of an argv element: `./node_modules/.bin/jest.cmd` -> `jest`."""
    name = re.split(r"[/\\]", str(arg))[-1].lower()
    return re.sub(r"\.(cmd|exe|bat|ps1|js|mjs|cjs)$", "", name)


def _runner_kind(spec):
    """Which red rules apply, decided by the command's argv whatever its source.
    Commands that match no known runner get the simple rule."""
    cmd = [str(a) for a in spec.command]
    if any("pytest" in a for a in cmd):
        return "pytest"
    if cmd[:2] == ["go", "test"]:
        return "go"
    progs = [_prog(a) for a in cmd]
    if "jest" in progs or "vitest" in progs:
        return "js"
    if progs and progs[0] in ("npm", "yarn", "pnpm", "bun") and "test" in cmd:
        return "js"
    if spec.source == "tests":
        return "js"  # _targeted only builds JS runner commands beyond pytest and go
    return "generic"


def _unclean(spec, red):
    """Why a failing baseline run is not evidence that tests ran and failed, or None."""
    out, code = red["output"], red["code"]
    if _env_failure(red):
        return "baseline could not run the repro (environment)"
    kind = _runner_kind(spec)
    if kind == "pytest" and code != 1:
        return f"baseline could not run the repro cleanly (pytest exit {code})"
    if kind == "js" and _JS_UNCLEAN.search(out):
        return "baseline could not run the repro cleanly (test suite failed to load)"
    if kind == "go" and _GO_UNCLEAN.search(out):
        return "baseline could not run the repro cleanly (go build or setup failed)"
    if kind == "go" and "--- FAIL" not in out:
        return "baseline could not run the repro cleanly (no failing go test reported)"
    return None


def _judge(claim, spec, cmd, red, green):
    if _env_failure(green):
        return Result(claim, "redgreen", cmd, "current tree could not run the repro (environment):\n"
                      + green["output"][-2000:], "inconclusive", 0.3)
    if green["code"] != 0:
        return Result(claim, "redgreen", cmd, "current tree: repro fails\n" + green["output"][-3000:], "fail")
    why = _unclean(spec, red) if red["code"] != 0 else None
    if why:
        return Result(claim, "redgreen", cmd, why + ":\n" + red["output"][-2000:], "inconclusive", 0.3)
    if red["code"] != 0:
        return Result(claim, "redgreen", cmd, "fix proven: repro failed before the change and passes now\n"
                      + "baseline output:\n" + red["output"][-1500:], "pass")
    f = Finding("repro-already-green", spec.copy_files[0] if spec.copy_files else "", 0,
                "repro passes on the baseline without your change, so it does not prove the fix")
    return suspect_result(claim, "redgreen", "fix not proven", [f], command=cmd)


def _cleanup(root, wt, links, deps):
    """Remove the worktree. Returns False when it was left in place on purpose.

    `deps` is where the node_modules link goes inside the worktree."""
    links = list(links)
    deps = Path(deps)
    # Only a candidate whose directory really lies inside the worktree, so a
    # redirected project dir can never make us unlink something of the user's.
    if deps not in links and _contained(wt, deps.parent) and _is_link(deps):
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


STALE_AGE = 3600


def _find_links(top):
    """Every link under `top`, without following any link or junction."""
    found, stack = [], [Path(top)]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if _is_link(e.path):
                found.append(Path(e.path))
            elif e.is_dir(follow_symlinks=False):
                stack.append(Path(e.path))
    return found


def _owner_repo(wt):
    """The main repository a worktree is registered with, from its .git file."""
    try:
        text = (Path(wt) / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    gitdir = Path(text[len("gitdir:"):].strip())
    try:
        common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
    except OSError:
        common = gitdir.parent.parent
    root = common.parent if common.name == ".git" else common
    return root if root.is_dir() else None


def _sweep(marker_root=None, now=None):
    """Remove baseline worktrees an interrupted run left behind (older than an hour).

    Same safety rules as a normal cleanup: every link is unlinked first, and a
    directory that still holds a link is left alone. Only each stale worktree's
    own registration is removed."""
    import time
    work = _home(marker_root) / "work"
    now = now or time.time()
    try:
        candidates = [p for p in work.glob("wt-*") if p.is_dir() and not _is_link(p)]
    except OSError:
        return
    for wt in candidates:
        try:
            if now - os.lstat(wt).st_mtime <= STALE_AGE:
                continue
            owner = _owner_repo(wt) or work
            _cleanup(owner, wt, _find_links(wt), Path(wt) / "node_modules")
        except Exception:
            continue


def run(claim, spec, root, base_commit, budget=None, marker_root=None):
    budget = budget or Budget(None)
    try:
        _sweep(marker_root)
    except Exception:
        pass
    if spec is None:
        return Result(claim, "redgreen", "", _NO_REPRO, "inconclusive", 0.0)
    cmd = " ".join(spec.command)
    rem = budget.remaining()
    if rem is not None and rem < MIN_BUDGET:
        return Result(claim, "redgreen", cmd, "deferred: not enough inline budget", "deferred", 0.0)
    st = {"top": Path(root), "wt": None, "links": []}
    left = False
    try:
        result = _attempt(claim, spec, cmd, root, base_commit, budget, marker_root, st)
    except gitutil.GitError as e:
        result = Result(claim, "redgreen", cmd, f"could not create baseline worktree: {e}", "inconclusive", 0.2)
    except OSError as e:
        result = Result(claim, "redgreen", cmd, f"could not prepare baseline worktree: {e}", "inconclusive", 0.2)
    finally:
        if st["wt"] is not None:
            try:
                left = not _cleanup(st["top"], st["wt"], st["links"], _sub(st["wt"], spec.cwd) / "node_modules")
            except Exception:
                pass
    if left:
        result.raw_output += (f"\nnote: baseline worktree left in place at {st['wt']} because a "
                              "dependency link could not be removed; remove the link, then the worktree")
    return result


def _sub(base, rel):
    return Path(base) / rel if rel else Path(base)


def _attempt(claim, spec, cmd, root, base_commit, budget, marker_root, st):
    top = gitutil.toplevel(root)
    st["top"] = top
    work = _home(marker_root) / "work"
    work.mkdir(parents=True, exist_ok=True)
    # A fresh empty directory we own, so cleanup can never hit anything else.
    wt = st["wt"] = Path(tempfile.mkdtemp(prefix="wt-", dir=str(work)))
    nohooks = str(work / ".no-hooks")
    gitutil.git(top, "-c", f"core.hooksPath={nohooks}", "worktree", "add", "--detach",
                str(wt), base_commit, timeout=budget.timeout())
    _copy_tests(top, wt, spec.copy_files)   # before linking: never copy through the link
    red_dir, green_dir = _sub(wt, spec.cwd), _sub(top, spec.cwd)
    if not red_dir.is_dir() or not _contained(wt, red_dir):
        return Result(claim, "redgreen", cmd, f"baseline has no project directory {spec.cwd!r}",
                      "inconclusive", 0.2)
    st["links"] = _link_deps(green_dir, red_dir)
    red = run_command(spec.command, cwd=red_dir, timeout=budget.timeout(), env=_py_env(red_dir))
    if red.get("timed_out"):
        return Result(claim, "redgreen", cmd, "deferred: baseline run timed out", "deferred", 0.0)
    green = run_command(spec.command, cwd=green_dir, timeout=budget.timeout(), env=_py_env(green_dir))
    if green.get("timed_out"):
        return Result(claim, "redgreen", cmd, "deferred: current run timed out", "deferred", 0.0)
    return _judge(claim, spec, cmd, red, green)
