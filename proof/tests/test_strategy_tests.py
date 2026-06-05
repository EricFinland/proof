from pathlib import Path
from proofkit.strategies.tests import verify_tests

FIX = Path(__file__).resolve().parent / "fixtures"


def test_pass_fixture_passes():
    r = verify_tests("tests pass", root=FIX / "tests_pass")
    assert r.verdict == "pass"


def test_fail_fixture_fails():
    r = verify_tests("tests pass", root=FIX / "tests_fail")
    assert r.verdict == "fail"
    assert "test_bad" in r.raw_output or "assert" in r.raw_output.lower()
