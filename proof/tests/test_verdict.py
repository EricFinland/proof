from proofkit.strategies.base import Result
from proofkit.verdict import aggregate


def _r(v):
    return Result("c", "tests", "cmd", "out", v)


def test_any_fail_is_fail():
    assert aggregate([_r("pass"), _r("fail")]) == "fail"


def test_all_pass_is_pass():
    assert aggregate([_r("pass"), _r("pass")]) == "pass"


def test_only_inconclusive_is_inconclusive():
    assert aggregate([_r("inconclusive")]) == "inconclusive"


def test_empty_is_inconclusive():
    assert aggregate([]) == "inconclusive"
