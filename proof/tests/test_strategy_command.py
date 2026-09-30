import os

import pytest

from proofkit.strategies.command import verify_command


def test_command_pass(tmp_path):
    r = verify_command("it runs", root=tmp_path, command="python -c print(1)")
    assert r.verdict == "pass"


def test_command_fail(tmp_path):
    # Windows-adjusted: use exit(2) builtin instead of "import sys;sys.exit(2)"
    # because shlex.split(..., posix=False) splits on spaces before semicolons,
    # turning "import sys;sys.exit(2)" into two args ['import', 'sys;sys.exit(2)'].
    r = verify_command("it runs", root=tmp_path, command="python -c exit(2)")
    assert r.verdict == "fail"


@pytest.mark.skipif(os.name != "nt", reason="PATHEXT resolution is Windows only")
def test_run_command_resolves_cmd_shim_on_path(tmp_path, monkeypatch):
    from proofkit.strategies.base import run_command
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "proofshim.cmd").write_text("@echo shim says hi\r\n", encoding="utf-8")
    (bin_dir / "proofbat.bat").write_text("@echo bat says hi\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    r = run_command(["proofshim"], cwd=tmp_path, timeout=30)
    assert r["code"] == 0 and "shim says hi" in r["output"], r
    r = run_command(["proofbat"], cwd=tmp_path, timeout=30, env=dict(os.environ))
    assert r["code"] == 0 and "bat says hi" in r["output"], r
