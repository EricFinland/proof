from pathlib import Path
import proofkit

ROOT = Path(__file__).resolve().parents[2]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_version():
    assert proofkit.__version__ == "3.0.0"
    assert '"version": "3.0.0"' in _read(".claude-plugin/plugin.json")


def test_config_reference_lists_v3_keys():
    text = _read("proof/references/configuration.md")
    for key in ("inline_budget", "command_timeout", "[baseline]", "[tamper]", "disable", "[repro]"):
        assert key in text, key


def test_docs_mention_suspect_and_exit_3():
    assert "SUSPECT" in _read("README.md")
    ev = _read("proof/references/evidence-format.md").lower()
    assert "exit code 3" in ev or "exit 3" in ev


def test_no_em_dashes_in_docs():
    for rel in ("README.md", "proof/SKILL.md", *[str(p.relative_to(ROOT)) for p in (ROOT / "proof/references").glob("*.md")]):
        assert "\u2014" not in _read(rel), rel


def _capture_timeout(monkeypatch):
    from proofkit import verdict
    seen = {}

    def fake_run_claims(claims, root, budget=None, command_timeout=None):
        seen["command_timeout"] = command_timeout
        return []

    monkeypatch.setattr(verdict, "run_claims", fake_run_claims)
    return verdict, seen


def test_command_timeout_is_honored_by_check(tmp_path, monkeypatch):
    (tmp_path / ".proof.toml").write_text("[verify]\ncommand_timeout = 7\n", encoding="utf-8")
    verdict, seen = _capture_timeout(monkeypatch)
    verdict.run_check("all tests pass", root=str(tmp_path), out_dir=str(tmp_path))
    assert seen["command_timeout"] == 7


def test_command_timeout_is_honored_by_verify(tmp_path, monkeypatch):
    (tmp_path / ".proof.toml").write_text("[verify]\ncommand_timeout = 9\n", encoding="utf-8")
    tp = tmp_path / "t.jsonl"
    tp.write_text('{"type": "assistant", "message": {"role": "assistant", "content": '
                  '[{"type": "text", "text": "All done, tests pass."}]}}\n', encoding="utf-8")
    verdict, seen = _capture_timeout(monkeypatch)
    verdict.run_verify(transcript=str(tp), root=str(tmp_path), out_dir=str(tmp_path))
    assert seen["command_timeout"] == 9


def test_command_timeout_defaults_to_600(tmp_path, monkeypatch):
    verdict, seen = _capture_timeout(monkeypatch)
    verdict.run_check("all tests pass", root=str(tmp_path), out_dir=str(tmp_path))
    assert seen["command_timeout"] == 600
