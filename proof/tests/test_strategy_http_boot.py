"""Tests for Task 10.2: local server boot path."""
import shutil
import socket
import time
import urllib.request
import urllib.error
from pathlib import Path

from proofkit.strategies.http import verify_http

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "http_app"


def _free_port():
    """Return an OS-assigned free port number."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _copy_fixture(tmp_path):
    """Copy fixture directory into tmp_path so we can write .proof.toml alongside."""
    app_dir = tmp_path / "http_app"
    shutil.copytree(str(FIXTURE_DIR), str(app_dir))
    return app_dir


def _write_toml(app_dir, port):
    toml = f'[http]\nserve = "python app.py {port}"\n'
    (app_dir / ".proof.toml").write_text(toml, encoding="utf-8")


def _server_gone(url, timeout=5):
    """Poll until url raises connection error or timeout; return True if gone."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            time.sleep(0.3)
        except Exception:
            return True
    return False


def test_boot_verifies_and_tears_down(tmp_path):
    """Boot a local server, verify /health, confirm server is torn down after."""
    port = _free_port()
    app_dir = _copy_fixture(tmp_path)
    _write_toml(app_dir, port)

    url = f"http://127.0.0.1:{port}/health"
    claim = f'GET {url} returns 200 with "ok"'

    r = verify_http(claim, root=str(app_dir))

    assert r.verdict == "pass", f"Expected pass, got {r.verdict}: {r.raw_output}"

    # Server should be gone
    assert _server_gone(url, timeout=5), "Server process was not torn down"


def test_no_serve_source_is_inconclusive(tmp_path):
    """No serve command anywhere -> inconclusive."""
    port = _free_port()
    app_dir = _copy_fixture(tmp_path)
    # Write .proof.toml WITHOUT serve key, so there's no serve source
    (app_dir / ".proof.toml").write_text("[http]\nbase_url = \"http://127.0.0.1\"\n", encoding="utf-8")

    url = f"http://127.0.0.1:{port}/health"
    claim = f"GET {url} returns 200"

    r = verify_http(claim, root=str(app_dir))

    assert r.verdict == "inconclusive", f"Expected inconclusive, got {r.verdict}: {r.raw_output}"
    assert "no serve command" in r.raw_output.lower()
