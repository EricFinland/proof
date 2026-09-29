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
