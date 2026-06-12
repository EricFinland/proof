import re
import urllib.request
import urllib.error

from proofkit.strategies import register
from proofkit.strategies.base import Result
from proofkit.config import load_config, cfg_get

_URL_RE = re.compile(r"https?://[^\s)]+")
_STATUS_RE = re.compile(r'(?:returns?|status)\s+(\d{3})\b', re.I)
_WITH_RE = re.compile(r'(?:with|containing)\s+"([^"]+)"', re.I)


def parse_http_claim(claim, cfg):
    """Return (url, want_status, want_body) parsed from a claim string and config."""
    m_url = _URL_RE.search(claim)
    if m_url:
        url = m_url.group(0)
    else:
        url = cfg_get(cfg, "http", "base_url", default="")

    # status: find 3-digit number; default 200
    want_status = "200"
    m_status = _STATUS_RE.search(claim)
    if m_status:
        want_status = m_status.group(1)

    # body: with "..." or containing "..."
    want_body = None
    m_body = _WITH_RE.search(claim)
    if m_body:
        want_body = m_body.group(1)

    return url, want_status, want_body


def _attempt(url):
    """GET url once. Returns (status_code, body_str) or raises urllib.error.URLError."""
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            code = resp.getcode()
            body = resp.read(2000).decode("utf-8", "ignore")
            return code, body
    except urllib.error.HTTPError as e:
        return e.code, str(e)


def _is_local(url):
    m = re.match(r"https?://([^/:]+)", url)
    if not m:
        return False
    host = m.group(1).lower()
    return host in ("localhost", "127.0.0.1")


def _boot_and_verify(claim, root, url, want_status, want_body, cfg):
    """Try to find a serve command, boot the server, verify, then teardown."""
    import os
    import sys
    import shlex
    import subprocess
    import time
    import json
    from pathlib import Path

    root_path = Path(root)

    # Resolve serve command from sources in priority order
    serve_cmd = cfg_get(cfg, "http", "serve")
    if not serve_cmd:
        pkg_json = root_path / "package.json"
        if pkg_json.is_file():
            try:
                pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
                scripts = pkg.get("scripts", {})
                serve_cmd = scripts.get("dev") or scripts.get("start")
            except Exception:
                pass
    if not serve_cmd:
        procfile = root_path / "Procfile"
        if procfile.is_file():
            for line in procfile.read_text(encoding="utf-8").splitlines():
                if line.startswith("web:"):
                    serve_cmd = line[4:].strip()
                    break

    if not serve_cmd:
        return Result(
            claim, "http", url,
            "server not running and no serve command found",
            "inconclusive", 0.3,
        )

    # Boot
    kwargs = {
        "cwd": str(root_path),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if sys.platform == "win32":
        cmd = shlex.split(serve_cmd, posix=False)
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        cmd = shlex.split(serve_cmd)
        kwargs["start_new_session"] = True

    p = subprocess.Popen(cmd, **kwargs)
    try:
        # Poll until ready (max 30s)
        deadline = time.time() + 30
        ready = False
        while time.time() < deadline:
            try:
                code, body = _attempt(url)
                ready = True
                break
            except Exception:
                time.sleep(0.5)

        if not ready:
            try:
                stderr_out = p.stderr.read(1000).decode("utf-8", "ignore") if p.stderr else ""
            except Exception:
                stderr_out = ""
            return Result(
                claim, "http", url,
                f"server did not become ready within 30s. stderr: {stderr_out}",
                "inconclusive", 0.3,
            )

        # Evaluate verdict
        return _evaluate(claim, url, code, body, want_status, want_body)
    finally:
        # Always teardown
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                    capture_output=True,
                )
            else:
                os.killpg(os.getpgid(p.pid), __import__("signal").SIGTERM)
        except Exception:
            pass
        try:
            p.wait(timeout=5)
        except Exception:
            pass


def _evaluate(claim, url, code, body, want_status, want_body):
    if str(code) != str(want_status):
        return Result(claim, "http", url, f"HTTP {code}\n{body}", "fail")
    if want_body is not None and want_body not in body:
        return Result(claim, "http", url, f"body missing expected substring\n{body[:2000]}", "fail")
    return Result(claim, "http", url, f"HTTP {code}\n{body}", "pass")


@register("http")
def verify_http(claim, root, command=None, expectation=None):
    cfg = load_config(root)

    # Backward-compat: command= is the URL, expectation= is the wanted status
    if command:
        url = command
        want_status = expectation or "200"
        want_body = None
        # Still check for body pattern in claim
        m_body = _WITH_RE.search(claim)
        if m_body:
            want_body = m_body.group(1)
    else:
        url, want_status, want_body = parse_http_claim(claim, cfg)

    if not url:
        return Result(claim, "http", "", "no URL in claim", "inconclusive", 0.2)

    try:
        code, body = _attempt(url)
    except urllib.error.URLError as e:
        # Connection refused or unreachable
        if _is_local(url):
            # Try booting a local server
            return _boot_and_verify(claim, root, url, want_status, want_body, cfg)
        else:
            # Non-local URL unreachable = deployed claim is a lie
            return Result(
                claim, "http", url,
                f"non-local URL unreachable (deploy claim failed): {e}",
                "fail", 1.0,
            )
    except Exception as e:
        return Result(claim, "http", url, f"request failed: {e}", "fail")

    return _evaluate(claim, url, code, body, want_status, want_body)
