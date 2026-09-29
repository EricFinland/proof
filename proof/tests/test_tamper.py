from pathlib import Path

from proofkit import tamper
from proofkit.changeset import ChangeSet, FileChange


def cs(*files):
    return ChangeSet("base", False, list(files))


def fc(path, status="M", added=(), removed=()):
    return FileChange(path, status, list(added), list(removed))


def rules(changes, root=".", cfg=None):
    return sorted(f.rule for f in tamper.analyze(changes, root, cfg or {}))


# ---- positives
def test_test_file_deleted():
    assert rules(cs(fc("tests/test_a.py", "D", removed=[(1, "def test_a():")]))) == ["test-file-deleted"]


def test_test_removed():
    assert rules(cs(fc("tests/test_a.py", removed=[(5, "def test_b():"), (6, "    assert f() == 2")]))) == ["test-removed"]


def test_skip_variants():
    for line in ["@pytest.mark.skip", "@pytest.mark.xfail(reason='x')", "    pytest.skip('later')",
                 "it.skip('works', () => {", "xit('works', () => {", "describe.skip('x', () => {",
                 "\tt.Skip(\"flaky\")", "#[ignore]", "@unittest.skip('x')"]:
        path = "src/lib_test.go" if "t.Skip" in line else ("src/lib.rs" if "#[" in line else "tests/test_a.py")
        assert rules(cs(fc(path, added=[(1, line)]))) == ["skip-added"], line


def test_only_added():
    assert rules(cs(fc("src/a.test.ts", added=[(3, "  it.only('x', () => {")]))) == ["only-added"]


def test_trivial_assert():
    assert rules(cs(fc("tests/test_a.py", added=[(4, "    assert True")]))) == ["assert-gutted"]
    assert rules(cs(fc("a.spec.js", added=[(4, "expect(true).toBe(true)")]))) == ["assert-gutted"]


def test_assert_removed_without_replacement():
    assert rules(cs(fc("tests/test_a.py", removed=[(7, "    assert total == 3")]))) == ["assert-gutted"]


def test_runner_neutered_package_json():
    assert rules(cs(fc("package.json", added=[(5, '    "test": "jest || true",')]))) == ["runner-neutered"]
    assert rules(cs(fc("package.json", added=[(5, '    "test": "jest --passWithNoTests",')]))) == ["runner-neutered"]


def test_runner_neutered_pytest_cfg():
    assert rules(cs(fc("pytest.ini", added=[(2, 'addopts = -k "not slow"')]))) == ["runner-neutered"]
    assert rules(cs(fc("pyproject.toml", added=[(9, 'addopts = "--deselect tests/test_a.py::test_x"')]))) == ["runner-neutered"]


def test_runner_neutered_ci_and_proof_toml():
    assert rules(cs(fc(".github/workflows/ci.yml", added=[(20, "        run: pytest || true")]))) == ["runner-neutered"]
    assert rules(cs(fc(".proof.toml", added=[(2, 'test = "true"')]))) == ["runner-neutered"]


def test_runner_neutered_makefile_test_target(tmp_path):
    (tmp_path / "Makefile").write_text("clean:\n\trm -rf build || true\ntest:\n\tpytest || true\n", encoding="utf-8")
    assert rules(cs(fc("Makefile", added=[(4, "\tpytest || true")])), root=tmp_path) == ["runner-neutered"]


# ---- traps (must stay silent)
def test_deleting_test_with_its_feature_is_fine():
    assert rules(cs(fc("tests/test_foo.py", "D", removed=[(1, "def test_foo():")]),
                    fc("src/foo.py", "D", removed=[(1, "def foo():")]))) == []


def test_moved_skip_is_net_zero():
    assert rules(cs(fc("tests/test_a.py", added=[(9, "@pytest.mark.skip")], removed=[(3, "@pytest.mark.skip")]))) == []


def test_commented_only_and_skip_ignored():
    assert rules(cs(fc("a.test.js", added=[(1, "// it.only('x', () => {"), (2, "# it.skip(")]))) == []


def test_unrelated_or_true_ignored(tmp_path):
    assert rules(cs(fc("package.json", added=[(7, '    "clean": "rm -rf dist || true",')]))) == []
    (tmp_path / "Makefile").write_text("clean:\n\trm -rf build || true\n", encoding="utf-8")
    assert rules(cs(fc("Makefile", added=[(2, "\trm -rf build || true")])), root=tmp_path) == []


def test_renamed_test_is_net_zero():
    assert rules(cs(fc("tests/test_a.py", added=[(1, "def test_new_name():")], removed=[(1, "def test_old_name():")]))) == []


def test_changed_assert_is_net_zero():
    assert rules(cs(fc("tests/test_a.py", added=[(2, "    assert x == 2")], removed=[(2, "    assert x == 1")]))) == []


def test_non_test_file_ignored():
    assert rules(cs(fc("src/net.py", removed=[(3, "def test_connection():")]))) == []


def test_disable_and_enabled_flags():
    c = cs(fc("tests/test_a.py", added=[(1, "@pytest.mark.skip")]))
    assert rules(c, cfg={"tamper": {"disable": ["skip-added"]}}) == []
    assert rules(c, cfg={"tamper": {"enabled": False}}) == []


def test_to_result_headline():
    fs = tamper.analyze(cs(fc("tests/test_a.py", added=[(1, "@pytest.mark.skip"), (5, "@pytest.mark.skip")]),
                           fc("tests/test_b.py", "D", removed=[(1, "def test_b():")])), ".", {})
    r = tamper.to_result("tests pass", fs)
    assert r.verdict == "suspect" and r.method == "tamper"
    assert r.raw_output.splitlines()[0] == "possible test tampering: 1 test file deleted and 2 skips added"
    assert tamper.to_result("x", []) is None


def test_integration_with_real_repo(git_repo, tmp_path):
    from proofkit import baseline, changeset
    git_repo.write("tests/test_a.py", "def test_a():\n    assert 1\n")
    git_repo.commit()
    b = baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    git_repo.write("tests/test_a.py", "import pytest\n\n@pytest.mark.skip\ndef test_a():\n    assert 1\n")
    assert "skip-added" in rules(changeset.compute(git_repo.path, b), root=git_repo.path)
