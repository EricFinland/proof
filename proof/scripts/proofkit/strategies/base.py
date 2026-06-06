import subprocess
from dataclasses import dataclass, asdict


@dataclass
class Result:
    claim: str
    method: str
    command: str
    raw_output: str
    verdict: str          # "pass" | "fail" | "inconclusive"
    confidence: float = 1.0

    def to_dict(self):
        return asdict(self)


def run_command(cmd, cwd, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout)
        return {"code": p.returncode, "output": (p.stdout or "") + (p.stderr or "")}
    except FileNotFoundError:
        return {"code": 127, "output": f"command not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"code": -1, "output": "TIMEOUT"}
