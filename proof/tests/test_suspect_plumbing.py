import json
from proofkit.findings import Finding, findings_hash, is_comment_line, suspect_result
from proofkit.strategies.base import Result
from proofkit.verdict import finalize, print_outcome
from proofkit import ledger


def _f(line=3):
    return Finding("skip-added", "tests/test_a.py", line, "@pytest.mark.skip")


def test_hash_ignores_line_numbers():
    assert findings_hash([_f(3)]) == findings_hash([_f(9)])
    assert findings_hash([_f()]) != findings_hash([Finding("only-added", "x", 1, "it.only(")])


def test_is_comment_line():
    assert is_comment_line("  # it.only(") and is_comment_line("// x") and is_comment_line("")
    assert not is_comment_line("#[ignore]") and not is_comment_line("it.only(")


def test_render_omits_empty_parts():
    assert _f().render() == "skip-added: tests/test_a.py:3  @pytest.mark.skip"
    assert Finding("r", "f.py", 0, " x ").render() == "r: f.py  x"
    assert Finding("r", "", 0, "x").render() == "r:  x"


def test_suspect_report_json_and_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROOF_HOME", str(tmp_path / "home"))
    r = suspect_result("tests pass", "tamper", "possible test tampering: 1 skip added", [_f()])
    out = finalize([Result("tests pass", "tests", "pytest", "ok", "pass"), r], tmp_path, tmp_path)
    assert out.overall == "suspect" and out.exit_code == 3
    assert "SUSPECT -- tamper" in (tmp_path / "proof-report.md").read_text(encoding="utf-8")
    print_outcome(out, as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit"] == 3
    assert payload["results"][1]["findings"][0]["rule"] == "skip-added"
    e = ledger.read_entries(root=tmp_path / "home")[-1]
    assert e["overall"] == "suspect" and e["suspects"] == ["tamper"]


def test_stats_count_suspects():
    s = ledger.compute_stats([{"overall": "pass"}, {"overall": "suspect"}, {"overall": "fail"}])
    assert s["suspects"] == 1 and s["honesty_rate"] == 1 / 3 and s["clean_streak"] == 0
    assert s["inconclusive"] == 0


def test_stats_cli_prints_gamed(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    proof = str(Path(__file__).resolve().parents[1] / "scripts" / "proof.py")
    ledger.append_entry({"overall": "pass", "claims": ["a"]}, root=tmp_path)
    ledger.append_entry({"overall": "suspect", "claims": ["b"], "suspects": ["tamper"]}, root=tmp_path)
    env = dict(os.environ, PROOF_HOME=str(tmp_path))
    r = subprocess.run([sys.executable, proof, "stats"], capture_output=True, text=True, env=env)
    lines = r.stdout.splitlines()
    assert lines[0] == "Honesty rate: 50% (2 verified, 1 lie caught)"
    assert lines[1] == "Gamed: 1"
