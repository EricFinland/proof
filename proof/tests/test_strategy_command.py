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
