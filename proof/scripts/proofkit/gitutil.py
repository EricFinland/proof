"""Thin git subprocess helpers. All paths are passed through as given."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_ID_ENV = {"GIT_AUTHOR_NAME": "proof", "GIT_AUTHOR_EMAIL": "proof@localhost",
           "GIT_COMMITTER_NAME": "proof", "GIT_COMMITTER_EMAIL": "proof@localhost"}


class GitError(Exception):
    pass


def git(root, *args, env=None, check=True, timeout=60):
    full_env = dict(os.environ)
    full_env.update(env or {})
    try:
        p = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=str(root),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=full_env, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise GitError(str(e))
    if check and p.returncode != 0:
        raise GitError(p.stderr.strip() or f"git {args[0]} failed")
    return p.stdout


def is_repo(root):
    try:
        return git(root, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except GitError:
        return False


def toplevel(root):
    return Path(git(root, "rev-parse", "--show-toplevel").strip())


def rev_parse(root, rev):
    try:
        out = git(root, "rev-parse", "--verify", "--quiet", rev).strip()
        return out or None
    except GitError:
        return None


def snapshot_tree(root):
    """Tree SHA of the working tree, untracked files included, ignored excluded.

    Uses a copy of the index so the user's real index is never written.
    """
    real = Path(git(root, "rev-parse", "--git-path", "index").strip())
    if not real.is_absolute():
        real = Path(root) / real
    fd, tmp = tempfile.mkstemp(prefix="proof-index-")
    os.close(fd)
    try:
        if real.exists():
            shutil.copyfile(real, tmp)
        else:
            os.remove(tmp)
        env = {"GIT_INDEX_FILE": tmp}
        git(root, "add", "-A", env=env)
        return git(root, "write-tree", env=env).strip()
    finally:
        for p in (tmp, tmp + ".lock"):
            try:
                os.remove(p)
            except OSError:
                pass


def commit_tree(root, tree, parent=None, message="proof baseline"):
    args = ["commit-tree", tree, "-m", message]
    if parent:
        args += ["-p", parent]
    return git(root, *args, env=_ID_ENV).strip()


def update_ref(root, ref, sha):
    git(root, "update-ref", ref, sha)


def delete_ref(root, ref):
    git(root, "update-ref", "-d", ref, check=False)
