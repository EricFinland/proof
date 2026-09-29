import json

from proofkit import baseline, classifier, hookflow, scope
from proofkit.changeset import ChangeSet, FileChange


def cs(*files, approximate=False):
    return ChangeSet("b", approximate, list(files))


def fc(path, added=(), removed=(), status="M"):
    return FileChange(path, status, list(added), list(removed))


def rules(msg, changes):
    return sorted(f.rule for f in scope.analyze(msg, changes))


def test_claim_kinds():
    assert classifier.is_fix_claim("The bug is fixed.")
    assert classifier.is_fix_claim("I've fixed the crash in the parser.")
    assert classifier.is_change_claim("I've added `parse_config` to `config.py`.")
    assert classifier.is_change_claim("I implemented retries.")
    assert not classifier.is_change_claim("All tests pass.")


def test_named_items():
    paths, syms = scope.named_items("I added `parse_config()` to `src/config.py`. The `foo` helper was fine.")
    assert paths == ["src/config.py"] and syms == ["parse_config"]
    _, syms2 = scope.named_items("I implemented `Loader.load_all`.")
    assert syms2 == ["load_all"]


def test_empty_change():
    assert rules("I fixed the bug.", cs()) == ["empty-change"]


def test_docs_only_and_comment_only():
    assert rules("I fixed the bug.", cs(fc("README.md", added=[(1, "fixed")]))) == ["docs-only"]
    assert rules("I fixed the bug.", cs(fc("src/a.py", added=[(1, "# handle None")]))) == ["docs-only"]


def test_named_path_and_symbol():
    c = cs(fc("src/config.py", added=[(3, "def parse_config(path):")]))
    assert rules("I added `parse_config` to `config.py`.", c) == []
    assert rules("I added `parse_config` to `loader.py`.", c) == ["named-path-unchanged"]
    c2 = cs(fc("src/config.py", added=[(9, "x = 1")]))
    assert rules("I added `parse_config` to `config.py`.", c2) == ["named-symbol-missing"]


def test_skips():
    assert scope.analyze("I fixed the bug.", None) == []
    assert scope.analyze("I fixed the bug.", cs(approximate=True)) == []
    assert scope.analyze("All tests pass.", cs()) == []
    assert rules("I fixed the bug.", cs(fc(".proof.toml", added=[(1, "x")]))) == ["empty-change"]


def test_to_result():
    assert scope.to_result("c", []) is None
    r = scope.to_result("I fixed the bug.", scope.analyze("I fixed the bug.", cs()))
    assert r.verdict == "suspect" and r.method == "scope"
    assert "claim does not match the diff: empty-change" in r.raw_output


def _tp(tmp_path, text):
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": text}]}}), encoding="utf-8")
    return str(f)


def _stop(tmp_path, cwd, active=False, text="I fixed the bug."):
    return hookflow.decide_stop({"session_id": "s", "transcript_path": _tp(tmp_path, text),
        "stop_hook_active": active}, cwd, marker_root=tmp_path / "home")


def test_hook_blocks_docs_only_fix_claim(git_repo, tmp_path):
    git_repo.write("README.md", "hello\n")
    git_repo.write("src/a.py", "x = 1\n")
    git_repo.commit()
    baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    git_repo.write("README.md", "hello\nfixed\n")
    out = _stop(tmp_path, git_repo.path)
    assert out["decision"] == "block" and "docs-only" in out["reason"]
