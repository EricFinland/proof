"""Tests for config-aware command resolution in run_verify (Task 7.2)."""
import json
from pathlib import Path
from proofkit.verdict import run_verify


def _make_transcript(tmp_path, text):
    t = tmp_path / "t.jsonl"
    t.write_text(
        json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            },
        }),
        encoding="utf-8",
    )
    return str(t)


def test_config_command_used_when_no_runner(tmp_path):
    """Repo with .proof.toml only (no detectable runner) -> uses config command."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".proof.toml").write_text(
        '[commands]\ntests = "python -c exit(0)"\n', encoding="utf-8"
    )
    transcript = _make_transcript(tmp_path, "All done, tests pass.")
    code = run_verify(transcript=transcript, root=str(repo), out_dir=str(tmp_path))
    assert code == 0, "Expected pass when config command exits 0"


def test_config_command_fails_when_exit_nonzero(tmp_path):
    """Config command that exits non-zero -> fail verdict."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".proof.toml").write_text(
        '[commands]\ntests = "python -c exit(1)"\n', encoding="utf-8"
    )
    transcript = _make_transcript(tmp_path, "All done, tests pass.")
    code = run_verify(transcript=transcript, root=str(repo), out_dir=str(tmp_path))
    assert code == 1, "Config command exit(1) should produce fail verdict"


def test_config_beats_auto_detect(tmp_path):
    """When both pyproject.toml (triggers pytest auto-detect) and .proof.toml
    [commands] test = "python -c exit(0)" are present, the config command wins.
    The runner would run pytest which has no tests and would exit non-zero or
    pass vacuously; the key signal is that we use the config-pinned command.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    # pyproject.toml triggers auto-detect of pytest
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    # Config command exits 0; if auto-detect wins it runs pytest (which may vary)
    # We pin a config command that succeeds to assert config takes priority.
    (repo / ".proof.toml").write_text(
        '[commands]\ntests = "python -c exit(0)"\n', encoding="utf-8"
    )
    transcript = _make_transcript(tmp_path, "All done, tests pass.")
    code = run_verify(transcript=transcript, root=str(repo), out_dir=str(tmp_path))
    assert code == 0, ".proof.toml command should take precedence over auto-detected runner"


def test_missing_config_key_still_inconclusive(tmp_path):
    """Config with no matching strategy key -> still inconclusive (no runner)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # Toml exists but has no 'tests' key
    (repo / ".proof.toml").write_text(
        '[commands]\nbuild = "make build"\n', encoding="utf-8"
    )
    transcript = _make_transcript(tmp_path, "All done, tests pass.")
    code = run_verify(transcript=transcript, root=str(repo), out_dir=str(tmp_path))
    assert code == 2, "No matching config key and no runner -> inconclusive"


def test_config_command_not_applied_to_http_strategy(tmp_path):
    """Config [commands].tests does not bleed into http strategy."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".proof.toml").write_text(
        '[commands]\ntests = "python -c exit(0)"\n', encoding="utf-8"
    )
    # http claim: should still fail/inconclusive, not use the tests config
    transcript = _make_transcript(tmp_path, "The endpoint returns 200.")
    code = run_verify(transcript=transcript, root=str(repo), out_dir=str(tmp_path))
    assert code in (1, 2), "http claim without reachable URL should fail or be inconclusive"
