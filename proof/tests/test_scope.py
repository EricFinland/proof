import json

import pytest

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


# ---- Ruling R8 regression tests ----

def cs_root(root, *files):
    return ChangeSet("b", False, list(files), str(root))


def test_r8_1_symbol_in_place_edit(tmp_path):
    (tmp_path / "config.py").write_text("def parse_config(path):\n    if path is None:\n        return {}\n",
                                        encoding="utf-8")
    c = cs_root(tmp_path, fc("config.py", added=[(2, "    if path is None:"), (3, "        return {}")]))
    assert rules("I added a null check to `parse_config` and all tests pass.", c) == []
    # root can also come from the caller
    c2 = ChangeSet("b", False, [fc("config.py", added=[(2, "    if path is None:")])])
    assert scope.analyze("I added a null check to `parse_config`.", c2, str(tmp_path)) == []


def test_r8_1_symbol_boundary_and_removed_lines():
    c = cs(fc("src/a.py", added=[(1, "max_retries = 3")]))
    assert rules("I added `retries`.", c) == []
    c2 = cs(fc("src/a.py", added=[(1, "x = 1")], removed=[(1, "parse_config()")]))
    assert rules("I added `parse_config`.", c2) == []


def test_r8_1_basename_token():
    c = cs(fc("build/Makefile", added=[(1, "all:")]))
    assert rules("I added a `Makefile` target.", c) == []


def test_r8_1_still_caught(tmp_path):
    (tmp_path / "other.py").write_text("x = 1\n", encoding="utf-8")
    c = cs_root(tmp_path, fc("other.py", added=[(1, "x = 1")]))
    assert rules("I added `parse_config` to `config.py`.", c) == ["named-path-unchanged", "named-symbol-missing"]


def test_r8_1_unreadable_file_is_skipped(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01parse_config\x00")
    c = cs_root(tmp_path, fc("bin.dat", added=[(1, "x")]), fc("gone.py", status="D", removed=[(1, "y")]))
    assert rules("I added `parse_config`.", c) == ["named-symbol-missing"]


def test_r8_2_extraction():
    paths, syms = scope.named_items(
        "I added `requests` to `requirements.txt` and `pytest.ini`, and `src\\config.py` "
        "with `try/except`, `application/json`, `@types/node`, `N/A`, `v2.1`, `/etc/hosts`, "
        "`C:/x/y.py`, `https://x.io/a.py`, `.proof.toml`, `proof-report.md`, `.proof/x.json`.")
    assert paths == ["requirements.txt", "pytest.ini", "src/config.py"]
    assert syms == ["requests"]
    p2, _ = scope.named_items("I added `src/` and `./lib/x.c` and `../y.go`.")
    assert p2 == ["src/", "lib/x.c", "y.go"]


def test_r8_2_changed_basename_is_path():
    p, s = scope.named_items("I added a `Makefile` target.", ["build/Makefile"])
    assert p == ["Makefile"] and s == []
    p, s = scope.named_items("I added a `Makefile` target.", [])
    assert p == [] and s == ["Makefile"]


def test_r8_2_silent_cases():
    c = cs(fc("requirements.txt", added=[(1, "requests==2.31")]))
    assert rules("I added `requests` to `requirements.txt`. All tests pass.", c) == []
    c2 = cs(fc("src/a.py", added=[(1, "try:"), (2, "except OSError:")]))
    assert rules("I added error handling with `try/except`.", c2) == []


def test_r8_2_directory_token():
    c = cs(fc("src/a.py", added=[(1, "x = 1")]))
    assert rules("I added files under `src/`.", c) == []
    assert rules("I added files under `lib/`.", c) == ["named-path-unchanged"]
    assert rules("I added files under `src/`.", cs(fc("pkg/src/b.py", added=[(1, "x")]))) == []


def test_r8_2_proof_artifacts_not_named_paths():
    c = cs(fc("src/a.py", added=[(1, "x = 1")]))
    assert rules("I added a config in `.proof.toml` and `proof-report.md`.", c) == []
    assert rules("I fixed the bug.", cs(fc("proof-report.md", added=[(1, "x")]))) == ["empty-change"]


@pytest.mark.parametrize("path", ["requirements.txt", "CMakeLists.txt", "app/docs/page.tsx"])
def test_r8_3_not_documentation(path):
    assert rules("I fixed the bug.", cs(fc(path, added=[(1, "changed = True")]))) == []


def test_r8_3_documentation_still_doc():
    assert rules("I fixed the bug.", cs(fc("docs/conf.py", added=[(1, "x = 1")]))) == ["docs-only"]
    assert rules("I fixed the bug.", cs(fc("guide/intro.rst", added=[(1, "x")]))) == ["docs-only"]
    assert rules("I fixed the bug.", cs(fc("pkg/README.txt", added=[(1, "x")]))) == ["docs-only"]


def test_r8_4_is_comment_line():
    from proofkit.findings import is_comment_line
    for code in ("#include <string.h>", "#define X 1", "#undef X", "#if A", "#ifdef A", "#ifndef X",
                 "#elif B", "#else", "#endif", "#pragma once", "#error no", "#region r",
                 "#endregion", "#!/usr/bin/env python", "*args,", "**kwargs", "*.log"):
        assert not is_comment_line(code), code
    for comment in ("# note", "#", "* foo", "*/", "*", "/* x", "// y", "<!-- z"):
        assert is_comment_line(comment), comment


@pytest.mark.parametrize("path,line", [("src/a.c", "#include <string.h>"), ("a.h", "#ifndef X"),
                                       ("a.h", "#define X"), ("a.h", "#endif"), (".gitignore", "*.log")])
def test_r8_4_preprocessor_and_ignore_lines_are_code(path, line):
    assert rules("I fixed the bug.", cs(fc(path, added=[(1, line)]))) == []


@pytest.mark.parametrize("path", ["Dockerfile", "Makefile", ".gitignore", ".env"])
def test_r8_4_extensionless_and_dotfiles_are_code(path):
    assert rules("I fixed the bug.", cs(fc(path, added=[(1, "# a comment")]))) == []


def test_r8_5_empty_change_gating():
    for msg in ("I've added the event to your calendar. All done.",
                "I wrote up the findings above. All done.",
                "The bug is fixed in v2.1 upstream. It works now."):
        assert rules(msg, cs()) == [], msg
    assert rules("I fixed the bug.", cs()) == ["empty-change"]
    assert rules("I\u2019ve fixed the bug.", cs()) == ["empty-change"]
    assert rules("I have fixed the bug.", cs()) == ["empty-change"]
    assert rules("I added `parse_config` to `config.py`.", cs()) == ["empty-change"]


def test_r8_5_docs_only_gating():
    readme = cs(fc("README.md", added=[(1, "x")]))
    assert rules("I added a section to `README.md`.", readme) == []
    assert rules("I fixed the bug.", readme) == ["docs-only"]
    assert rules("I added `parse_config`.", readme) == ["docs-only", "named-symbol-missing"]
    assert rules("I added `src/a.py`.", readme) == ["docs-only", "named-path-unchanged"]


def test_r8_6_fix_patterns():
    assert not classifier.is_fix_claim("The header is fixed at the top, and it works now.")
    assert classifier.is_fix_claim("I\u2019ve fixed the bug.")
    assert classifier.is_fix_claim("The crash is now fixed.")
    assert classifier.is_fix_claim("It is fixed.")
    assert classifier.is_change_claim("I\u2019ve added retries.")
    assert not classifier.is_fix_claim("The tests are passing.")


def test_r8_7_docs_only_blocks_once_then_tells_user(git_repo, tmp_path):
    git_repo.write("README.md", "hello\n")
    git_repo.write("src/a.py", "x = 1\n")
    git_repo.commit()
    baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    git_repo.write("README.md", "hello\nfixed\n")
    first = _stop(tmp_path, git_repo.path)
    assert first["decision"] == "block" and "docs-only" in first["reason"]
    second = _stop(tmp_path, git_repo.path, active=True)
    assert "decision" not in second and "docs-only" in second["systemMessage"]
