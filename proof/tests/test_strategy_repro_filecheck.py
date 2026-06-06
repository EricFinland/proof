from proofkit.strategies.filecheck import verify_filecheck
from proofkit.strategies.repro import verify_repro


def test_filecheck_symbol_present(tmp_path):
    (tmp_path / "m.py").write_text("def handler(): return 1\n")
    r = verify_filecheck(
        "added handler()",
        root=tmp_path,
        command="handler",
        expectation="m.py",
    )
    assert r.verdict == "pass"


def test_filecheck_symbol_absent(tmp_path):
    (tmp_path / "m.py").write_text("def other(): return 1\n")
    r = verify_filecheck(
        "added handler()",
        root=tmp_path,
        command="handler",
        expectation="m.py",
    )
    assert r.verdict == "fail"


def test_repro_runs_command(tmp_path):
    r = verify_repro("bug fixed", root=tmp_path, command="python -c print(1)")
    assert r.verdict == "pass"
