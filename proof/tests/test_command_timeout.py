"""[verify] command_timeout also bounds the red-green repro runs of `check` and `verify`."""
import json
import time

from proofkit.verdict import run_check

SLOW = 'I fixed the bug.\nRepro: `python -c "import time; time.sleep(5)"`'


def test_check_redgreen_honours_command_timeout(git_repo, tmp_path, capsys):
    git_repo.write(".proof.toml", "[verify]\ncommand_timeout = 1\n")
    git_repo.write("calc.py", "X = 1\n")
    base = git_repo.commit()
    git_repo.write("calc.py", "X = 2\n")
    t0 = time.monotonic()
    code = run_check(SLOW, root=str(git_repo.path), out_dir=str(tmp_path), as_json=True,
                     since=base)
    elapsed = time.monotonic() - t0
    payload = json.loads(capsys.readouterr().out)
    rg = [r for r in payload["results"] if r["method"] == "redgreen"]
    assert rg and rg[0]["verdict"] in ("deferred", "inconclusive"), payload
    assert code == 2
    assert elapsed < 5, elapsed


def test_directive_and_subagent_doc_ask_for_the_max_bash_timeout():
    from pathlib import Path
    from proofkit.hookflow import DIRECTIVE
    assert "600000" in DIRECTIVE
    doc = Path(__file__).resolve().parents[1] / "references" / "verifier-subagent.md"
    assert "600000" in doc.read_text(encoding="utf-8")
