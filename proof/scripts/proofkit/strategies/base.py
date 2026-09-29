import os
import re
import shlex
import subprocess
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


def run_command(cmd, cwd, timeout=DEFAULT_COMMAND_TIMEOUT, env=None):
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
        return {"code": p.returncode, "output": (p.stdout or "") + (p.stderr or ""),
                "timed_out": False}
    except FileNotFoundError:
        return {"code": 127, "output": f"command not found: {cmd[0]}", "timed_out": False}
    except subprocess.TimeoutExpired:
        return {"code": -1, "output": f"TIMEOUT after {timeout:.0f}s", "timed_out": True}


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
