import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, asdict, field

DEFAULT_COMMAND_TIMEOUT = 600


@dataclass
class Result:
    claim: str
    method: str
    command: str
    raw_output: str
    verdict: str          # "pass" | "fail" | "suspect" | "inconclusive" | "deferred"
    confidence: float = 1.0
    findings: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def split_command(cmd, windows=None):
    """Split a command string into argv. Lists pass through unchanged.

    POSIX quoting rules everywhere so quotes are stripped. On Windows, lone
    backslashes are doubled first so paths like C:\\tools survive.
    """
    if isinstance(cmd, (list, tuple)):
        return list(cmd)
    if not cmd:
        return []
    if windows is None:
        windows = os.name == "nt"
    if windows:
        cmd = re.sub(r'\\(?!")', r"\\\\", cmd)
    return shlex.split(cmd, posix=True)


def _resolve_program(cmd, env=None):
    """On Windows, find argv[0] the way a shell would (PATHEXT: .cmd, .bat, .exe).

    CreateProcess only appends .exe, so shims such as npm.cmd are otherwise not
    found. A name with a path separator or an extension is left alone, and so is
    a name that resolves to an .exe, which CreateProcess finds with its own search
    order.
    """
    if os.name != "nt" or not isinstance(cmd, (list, tuple)) or not cmd:
        return cmd
    prog = str(cmd[0])
    if "/" in prog or "\\" in prog or os.path.splitext(prog)[1]:
        return cmd
    found = shutil.which(prog, path=env.get("PATH") if env else None)
    if not found or os.path.splitext(found)[1].lower() in (".exe", ".com"):
        return cmd
    return [found] + list(cmd[1:])


def _kill_tree(p):
    """Kill the process and everything it started (its own process group)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                           capture_output=True, timeout=15)
        else:
            import signal
            os.killpg(p.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        p.kill()
    except OSError:
        pass


def _text(data):
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data or ""


def _close_pipes(p):
    # On Windows a reader thread may still hold a pipe, and closing it there can
    # block, so the close happens off the calling thread.
    def close():
        for f in (p.stdout, p.stderr):
            try:
                if f:
                    f.close()
            except Exception:
                pass
    import threading
    threading.Thread(target=close, daemon=True).start()


def run_command(cmd, cwd, timeout=DEFAULT_COMMAND_TIMEOUT, env=None):
    # Python validates cached bytecode by source mtime (whole seconds) and size,
    # so a same-size edit made within a second of the last run would execute the
    # old code. A fresh cache prefix per run forces compilation from source and
    # keeps __pycache__ out of the user's tree.
    env = dict(os.environ if env is None else env)
    prefix = tempfile.mkdtemp(prefix="proof-pycache-")
    env["PYTHONPYCACHEPREFIX"] = prefix
    try:
        return _run(cmd, cwd, timeout, env)
    finally:
        shutil.rmtree(prefix, ignore_errors=True)


def _run(cmd, cwd, timeout, env):
    cmd = _resolve_program(cmd, env)
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    try:
        p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", env=env, **group)
    except FileNotFoundError:
        return {"code": 127, "output": f"command not found: {cmd[0]}", "timed_out": False}
    try:
        out, err = p.communicate(timeout=timeout)
        return {"code": p.returncode, "output": (out or "") + (err or ""), "timed_out": False}
    except subprocess.TimeoutExpired:
        pass
    except BaseException:
        # Ctrl+C or any other error: the child runs in its own group, so nothing
        # else would stop it.
        _kill_tree(p)
        raise
    _kill_tree(p)
    try:
        out, err = p.communicate(timeout=5)
        read = (out or "") + (err or "")
    except subprocess.TimeoutExpired as e:
        # Something outside the tree still holds the pipes: keep what was read.
        read = _text(e.output) + _text(e.stderr)
        _close_pipes(p)
    except (OSError, ValueError):
        read = ""
    head = f"TIMEOUT after {timeout:.0f}s"
    return {"code": -1, "output": head + ("\n" + read[-3000:] if read.strip() else ""),
            "timed_out": True}


def verdict_for(res):
    if res.get("timed_out"):
        return "deferred"
    if res["code"] == 127:
        return "inconclusive"
    return "pass" if res["code"] == 0 else "fail"


class Budget:
    """Wall-clock budget shared by every check in one inline verification."""

    def __init__(self, seconds=None):
        self.deadline = None if seconds is None else time.monotonic() + float(seconds)

    def remaining(self):
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - time.monotonic())

    def exhausted(self):
        r = self.remaining()
        return r is not None and r < 1.0

    def timeout(self, default=DEFAULT_COMMAND_TIMEOUT):
        r = self.remaining()
        if r is None:
            return default
        return max(1.0, min(default, r))
