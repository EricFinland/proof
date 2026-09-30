from pathlib import Path
import proofkit

ROOT = Path(__file__).resolve().parents[2]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_version():
    assert proofkit.__version__ == "3.0.0"
    assert '"version": "3.0.0"' in _read(".claude-plugin/plugin.json")
    skill_readme = _read("proof/README.md")
    assert "v3.0.0" in skill_readme and "2.0.0" not in skill_readme


def test_config_reference_lists_v3_keys():
    text = _read("proof/references/configuration.md")
    for key in ("inline_budget", "command_timeout", "[baseline]", "[tamper]", "disable", "[repro]"):
        assert key in text, key


def test_docs_mention_suspect_and_exit_3():
    assert "SUSPECT" in _read("README.md")
    ev = _read("proof/references/evidence-format.md").lower()
    assert "exit code 3" in ev or "exit 3" in ev


def test_no_em_dashes_in_docs():
    for rel in ("README.md", "proof/README.md", "proof/SKILL.md", *[str(p.relative_to(ROOT)) for p in (ROOT / "proof/references").glob("*.md")]):
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


PASS_MEANING = "no check failed or looked gamed, and at least one check passed"


def test_pass_is_described_by_aggregate_semantics():
    for rel in ("README.md", "proof/SKILL.md"):
        assert PASS_MEANING in _read(rel).lower(), rel


def test_tamper_headline_example_follows_rule_order():
    ev = _read("proof/references/evidence-format.md")
    assert "possible test tampering: 1 test file deleted and 2 skips added" in ev
    assert "2 skips added and 1 test file deleted" not in ev


def test_design_mentions_report_and_proof_home_state():
    design = _read("README.md").split("## Design", 1)[1].split("\n## ", 1)[0]
    assert "proof-report.md" in design and "~/.proof" in design


def test_subject_name_exemption_scope_is_documented():
    row = [ln for ln in _read("proof/references/verifier-strategies.md").splitlines()
           if ln.startswith("| `test-removed`")][0]
    assert "def test_*" in row and "func Test*" in row and "only" in row


def test_baseline_refs_are_documented_as_visible_in_git_log_all():
    for rel in ("README.md", "proof/references/configuration.md"):
        text = _read(rel)
        assert "git log --all" in text and "untracked" in text, rel


def test_scope_empty_change_message_says_baseline():
    from proofkit import scope
    from proofkit.changeset import ChangeSet
    f = scope.analyze("I fixed the bug.", ChangeSet("b", False, [], ""))
    assert f[0].snippet == "no files changed since the baseline"


def test_no_em_dashes_in_changed_sources():
    for p in list((ROOT / "proof" / "scripts").rglob("*.py")) + list((ROOT / "proofml").rglob("*.py")):
        assert "\u2014" not in p.read_text(encoding="utf-8"), p
