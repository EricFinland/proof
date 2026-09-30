import sys
from pathlib import Path

import pytest
from proofkit import baseline, changeset


def _base(repo, tmp_path):
    return baseline.capture(repo.path, "s", marker_root=tmp_path / "home")


def test_statuses_and_lines(git_repo, tmp_path):
    git_repo.write("keep.py", "a\nb\nc\n")
    git_repo.write("gone.py", "x\n")
    git_repo.commit()
    b = _base(git_repo, tmp_path)
    git_repo.write("keep.py", "a\nB\nc\nd\n")
    git_repo.delete("gone.py")
    git_repo.write("new.py", "n1\nn2\n")
    cs = changeset.compute(git_repo.path, b)
    st = {f.path: f.status for f in cs.files}
    assert st == {"keep.py": "M", "gone.py": "D", "new.py": "A"}
    keep = cs.get("keep.py")
    assert (2, "b") in keep.removed and (2, "B") in keep.added and (4, "d") in keep.added
    assert cs.get("gone.py").removed == [(1, "x")]
    assert cs.get("new.py").added == [(1, "n1"), (2, "n2")]


def test_removed_line_starting_with_dashes(git_repo, tmp_path):
    git_repo.write("q.sql", "-- comment\nselect 1;\n")
    git_repo.commit()
    b = _base(git_repo, tmp_path)
    git_repo.write("q.sql", "select 1;\n")
    assert changeset.compute(git_repo.path, b).get("q.sql").removed == [(1, "-- comment")]


def test_proof_artifacts_filtered(git_repo, tmp_path):
    git_repo.write("a.py", "1\n"); git_repo.commit()
    b = _base(git_repo, tmp_path)
    git_repo.write("proof-report.md", "# report\n")
    git_repo.write(".proof/x.json", "{}\n")
    git_repo.write("tests/__pycache__/t.cpython-312.pyc", "bin\n")
    assert changeset.compute(git_repo.path, b).is_empty()


def test_empty_when_unchanged(git_repo, tmp_path):
    git_repo.write("a.py", "1\n"); git_repo.commit()
    assert changeset.compute(git_repo.path, _base(git_repo, tmp_path)).is_empty()


def test_for_claim_approximate_and_none(git_repo, tmp_path):
    git_repo.write("a.py", "1\n"); git_repo.commit()
    git_repo.write("a.py", "2\n")
    cs = changeset.for_claim(git_repo.path, session="missing", marker_root=tmp_path / "home")
    assert cs.approximate and cs.paths() == ["a.py"]
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    assert changeset.for_claim(nogit) is None


def test_form_feed_and_unicode_separator_do_not_split_lines(git_repo, tmp_path):
    git_repo.write("f.txt", "one\n")
    git_repo.commit()
    b = _base(git_repo, tmp_path)
    git_repo.write("f.txt", "one\na\x0cb\nc d\nlast\n")
    cs = changeset.compute(git_repo.path, b)
    assert cs.get("f.txt").added == [(2, "ab"), (3, "c d"), (4, "last")]


def test_path_with_space_keeps_lines(git_repo, tmp_path):
    git_repo.write("my file.txt", "one\ntwo\n")
    git_repo.commit()
    b = _base(git_repo, tmp_path)
    git_repo.write("my file.txt", "one\nTWO\n")
    git_repo.write("new doc.md", "n\n")
    cs = changeset.compute(git_repo.path, b)
    f = cs.get("my file.txt")
    assert f.added == [(2, "TWO")] and f.removed == [(2, "two")]
    assert cs.get("new doc.md").added == [(1, "n")]


def test_unquote_c_style_paths():
    u = changeset._unquote
    bs, q, tab = chr(92), chr(34), chr(9)
    assert u(q + 'a/we' + bs + q + 'ird name' + q) == 'a/we' + q + 'ird name'
    assert u(q + 'b/t' + bs + 't' + 'ab' + bs + bs + 'x' + q) == 'b/t' + tab + 'ab' + bs + 'x'
    assert u(q + 'a/caf' + bs + '303' + bs + '251' + q) == 'a/caf' + chr(0xe9)
    assert u('a/plain name.txt' + tab) == 'a/plain name.txt'
    assert u('/dev/null') == '/dev/null'


@pytest.mark.skipif(sys.platform == "win32", reason="double quote is not a legal filename character")
def test_path_with_double_quote_keeps_lines(git_repo, tmp_path):
    git_repo.write('we"ird.txt', "a\n")
    git_repo.commit()
    b = _base(git_repo, tmp_path)
    git_repo.write('we"ird.txt', "a\nb\n")
    assert changeset.compute(git_repo.path, b).get('we"ird.txt').added == [(2, "b")]


def test_subdir_root_scopes_changes(git_repo, tmp_path):
    git_repo.write("sub/a.py", "a\n")
    git_repo.write("other/b.py", "b\n")
    git_repo.commit()
    _base(git_repo, tmp_path)
    git_repo.write("sub/a.py", "a\nA\n")
    git_repo.write("other/b.py", "b\nB\n")
    git_repo.write("root.txt", "r\n")
    cs = changeset.for_claim(git_repo.path / "sub", session="s", marker_root=tmp_path / "home")
    assert cs.paths() == ["sub/a.py"]
    assert Path(cs.root).resolve() == git_repo.path.resolve()
    whole = changeset.for_claim(git_repo.path, session="s", marker_root=tmp_path / "home")
    assert whole.paths() == ["other/b.py", "root.txt", "sub/a.py"]


@pytest.mark.parametrize("key,value", [("diff.noprefix", "true"), ("diff.srcPrefix", "x/"),
                                       ("diff.dstPrefix", "y/"), ("diff.mnemonicPrefix", "true")])
def test_user_diff_prefix_config_does_not_drop_lines(git_repo, tmp_path, key, value):
    git_repo.git("config", key, value)
    git_repo.write("a/keep.py", "a1\n")
    git_repo.write("b/keep.py", "b1\n")
    git_repo.write("top.py", "t1\n")
    git_repo.commit()
    b = _base(git_repo, tmp_path)
    git_repo.write("a/keep.py", "a1\na2\n")
    git_repo.write("b/keep.py", "B1\n")
    git_repo.write("top.py", "t1\nt2\n")
    cs = changeset.compute(git_repo.path, b)
    assert cs.get("a/keep.py").added == [(2, "a2")]
    assert cs.get("b/keep.py").removed == [(1, "b1")] and cs.get("b/keep.py").added == [(1, "B1")]
    assert cs.get("top.py").added == [(2, "t2")]


def test_external_diff_and_textconv_config_are_ignored(git_repo, tmp_path):
    git_repo.write(".gitattributes", "*.py diff=weird\n")
    git_repo.git("config", "diff.weird.textconv", "false")
    git_repo.git("config", "diff.external", "false")
    git_repo.write("m.py", "m1\n")
    git_repo.commit()
    b = _base(git_repo, tmp_path)
    git_repo.write("m.py", "m1\nm2\n")
    cs = changeset.compute(git_repo.path, b)
    assert cs.get("m.py").added == [(2, "m2")]
