import json
from pathlib import Path

from proofkit.strategies.base import Result
from proofkit.verdict import aggregate, write_report, run_verify


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


def test_write_report_contains_receipts(tmp_path):
    results = [Result("tests pass", "tests", "pytest -q", "2 failed", "fail")]
    path = write_report(results, "fail", out_dir=tmp_path)
    txt = Path(path).read_text(encoding="utf-8")
    assert "FAIL" in txt and "pytest -q" in txt and "2 failed" in txt


def test_run_verify_fail_returns_code_1(tmp_path, monkeypatch):
    # transcript claims tests pass; fixture tests fail -> overall FAIL -> exit 1
    fix = Path(__file__).resolve().parent / "fixtures" / "tests_fail"
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "All done, tests pass."}]}}))
    code = run_verify(transcript=str(t), root=str(fix), out_dir=str(tmp_path))
    assert code == 1
