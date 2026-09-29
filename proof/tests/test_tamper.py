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


# ---- Ruling R6 regressions
# A. pooling across the changeset
def test_rename_with_skip_is_silent():
    old = fc("tests/test_a.py", "D", removed=[(1, "@pytest.mark.skip"), (2, "def test_a():")])
    new = fc("tests/test_b.py", "A", added=[(1, "@pytest.mark.skip"), (2, "def test_a():")])
    assert rules(cs(old, new)) == []


def test_test_moved_between_files_is_net_zero():
    a = fc("tests/test_a.py", removed=[(3, "def test_x():"), (4, "    assert x == 1")])
    b = fc("tests/test_b.py", added=[(9, "def test_x():"), (10, "    assert x == 1")])
    assert rules(cs(a, b)) == []


def test_skip_reason_edit_nets_to_zero():
    assert rules(cs(fc("tests/test_a.py", added=[(1, '@pytest.mark.skip(reason="flaky on CI")')],
                       removed=[(1, '@pytest.mark.skip(reason="flaky")')]))) == []
    assert rules(cs(fc("tests/test_a.py", added=[(1, "@pytest.mark.skip(reason='x')")],
                       removed=[(1, '@pytest.mark.skip(reason="x")')]))) == []


def test_extra_skip_beyond_removed_is_reported():
    c = cs(fc("tests/test_a.py", added=[(1, "@pytest.mark.skip"), (5, "@pytest.mark.skip")],
              removed=[(1, "@pytest.mark.skip")]))
    assert rules(c) == ["skip-added"]


# B. test-file-deleted scope
def test_deleting_non_test_files_under_tests_dir_is_silent():
    assert rules(cs(fc("tests/fixtures/old.json", "D", removed=[(1, "{}")]))) == []
    assert rules(cs(fc("tests/__init__.py", "D", removed=[(1, "")]))) == []
    assert rules(cs(fc("docs/spec/api.md", "D", removed=[(1, "# api")]))) == []


def test_deleted_test_moved_by_basename_is_silent():
    assert rules(cs(fc("tests/test_a.py", "D", removed=[(1, "def test_a():")]),
                    fc("tests/unit/test_a.py", "A", added=[(1, "def test_a():")]))) == []


def test_deleted_test_split_is_silent():
    assert rules(cs(fc("tests/test_a.py", "D", removed=[(1, "def test_one():"), (4, "def test_two():")]),
                    fc("tests/test_a1.py", "A", added=[(1, "def test_one():")]),
                    fc("tests/test_a2.py", "A", added=[(1, "def test_two():")]))) == []


def test_deleted_test_with_feature_package_is_silent():
    assert rules(cs(fc("tests/test_foo.py", "D", removed=[(1, "def test_foo():")]),
                    fc("src/foo/core.py", "D", removed=[(1, "x = 1")]),
                    fc("src/foo/__init__.py", "D", removed=[(1, "")]))) == []


# C. test-removed with the feature, and raises counted as assertions
def test_test_removed_with_its_feature_is_silent():
    t = fc("tests/test_utils.py", removed=[(5, "def test_old_feature():"), (6, "    assert old_feature() == 1")])
    s = fc("src/utils.py", removed=[(2, "def old_feature():")])
    assert rules(cs(t, s)) == []
    assert rules(cs(t)) == ["test-removed"]


def test_go_test_removed_with_its_feature_is_silent():
    t = fc("pkg/foo_test.go", removed=[(5, "func TestParseThing(t *testing.T) {")])
    s = fc("pkg/foo.go", removed=[(2, "func parseThing() {")])
    assert rules(cs(t, s)) == []


def test_assert_to_raises_is_net_zero():
    assert rules(cs(fc("tests/test_a.py", added=[(3, "    with pytest.raises(ValueError):")],
                       removed=[(3, "    assert f() is None")]))) == []


# D. focus rule scope
def test_model_fit_is_not_focus():
    assert rules(cs(fc("tests/test_model.py", added=[(2, "    model.fit(X_train, y_train)")]))) == []
    assert rules(cs(fc("src/a.test.ts", added=[(2, "  model.fit(X, y)")]))) == []


def test_fit_and_fdescribe_focus_in_js_only():
    assert rules(cs(fc("src/a.test.ts", added=[(2, "fit('works', () => {")]))) == ["only-added"]
    assert rules(cs(fc("src/a.test.ts", added=[(2, "fdescribe('suite', () => {")]))) == ["only-added"]
    assert rules(cs(fc("tests/test_a.py", added=[(2, "fit('works', 1)")]))) == []


# E. Rust scope
def test_rust_production_edits_are_silent():
    assert rules(cs(fc("src/lib.rs", added=[(4, "    let v = f()?;")],
                       removed=[(4, '    let v = f().expect("bad");')]))) == []
    assert rules(cs(fc("src/lib.rs", removed=[(4, "    assert!(x > 0);")]))) == []


def test_rust_test_dir_is_fully_testish():
    assert rules(cs(fc("tests/api.rs", removed=[(4, "    assert_eq!(a, b);")]))) == ["assert-gutted"]


def test_rust_src_test_removed_and_ignore_still_caught():
    assert rules(cs(fc("src/lib.rs", removed=[(3, "#[test]")]))) == ["test-removed"]
    assert rules(cs(fc("src/lib.rs", added=[(3, "#[ignore]")]))) == ["skip-added"]


# F. skip rule scope
def test_conditional_skips_are_silent():
    for line in ["@pytest.mark.skipif(sys.platform=='win32', reason='x')", "@unittest.skipUnless(HAS_X, 'x')",
                 "@unittest.skipIf(WIN, 'x')", "    np = pytest.importorskip('numpy')",
                 "it.todo('later')"]:
        assert rules(cs(fc("tests/test_a.py", added=[(1, line)]))) == [], line


def test_pytest_skip_in_conftest_is_silent():
    assert rules(cs(fc("tests/conftest.py", added=[(1, "        pytest.skip('no db')")]))) == []


def test_go_short_guard_is_silent():
    same = 'if testing.Short() { t.Skip("slow") }'
    assert rules(cs(fc("pkg/a_test.go", added=[(1, same)]))) == []
    above = [(1, "\tif testing.Short() {"), (2, '\t\tt.Skip("slow")')]
    assert rules(cs(fc("pkg/a_test.go", added=above))) == []
    assert rules(cs(fc("pkg/a_test.go", added=[(2, '\tt.Skip("flaky")')]))) == ["skip-added"]


def test_extra_skip_forms_are_caught():
    for line in ["pytestmark = pytest.mark.skip", "    marks=pytest.mark.skip,", '        self.skipTest("x")',
                 "  this.skip()", "it.skip.each([1])('x', () => {", "describe.skip.each([1])('x', () => {",
                 "test.fixme('x', () => {", "@unittest.expectedFailure"]:
        js = "skip(" in line or "each" in line or "fixme" in line
        path = "src/a.test.js" if js else "tests/test_a.py"
        assert rules(cs(fc(path, added=[(1, line)]))) == ["skip-added"], line


# G. runner-neutered scope
def test_neuter_scope_traps(tmp_path):
    assert rules(cs(fc("package.json", added=[(7, '    "posttest": "rimraf tmp || true",')]))) == []
    assert rules(cs(fc("package.json", added=[(7, '    "pretest": "jest || true",')]))) == []
    default = '    "test": "echo \\"Error: no test specified\\" && exit 1",'
    assert rules(cs(fc("package.json", added=[(7, default)]))) == []
    assert rules(cs(fc("package.json", added=[(7, '    "test:unit": "jest --passWithNoTests",')]))) == []
    assert rules(cs(fc(".github/workflows/ci.yml", added=[(9, "        run: npm ci || true")]))) == []
    (tmp_path / "Makefile").write_text("lint:\n\techo hi || true\ntest:\n\tpytest\n", encoding="utf-8")
    assert rules(cs(fc("Makefile", added=[(2, "\techo hi || true")])), root=tmp_path) == []
    (tmp_path / "Makefile").write_text("test:\n\techo starting || true\n", encoding="utf-8")
    assert rules(cs(fc("Makefile", added=[(2, "\techo starting || true")])), root=tmp_path) == []


def test_pytest_ignore_and_flake8_traps(tmp_path):
    assert rules(cs(fc("pyproject.toml", added=[(9, 'addopts = "-ra --ignore=build"')]))) == []
    (tmp_path / "tox.ini").write_text("[testenv]\ncommands =\n    flake8 --ignore=E501 src\n", encoding="utf-8")
    assert rules(cs(fc("tox.ini", added=[(3, "    flake8 --ignore=E501 src")])), root=tmp_path) == []
    assert rules(cs(fc("pytest.ini", added=[(2, "addopts = --ignore=tests/test_slow.py")]))) == ["runner-neutered"]


def test_pytest_section_lines_are_inspected(tmp_path):
    (tmp_path / "setup.cfg").write_text("[flake8]\nmax = 1\n[tool:pytest]\naddopts =\n    -k 'not slow'\n",
                                        encoding="utf-8")
    assert rules(cs(fc("setup.cfg", added=[(5, "    -k 'not slow'")])), root=tmp_path) == ["runner-neutered"]
    (tmp_path / "setup.cfg").write_text("[coverage]\nomit =\n    -k x\n", encoding="utf-8")
    assert rules(cs(fc("setup.cfg", added=[(3, "    -k x")])), root=tmp_path) == []


def test_tox_commands_neutered(tmp_path):
    (tmp_path / "tox.ini").write_text("[testenv]\ncommands = pytest || true\n", encoding="utf-8")
    assert rules(cs(fc("tox.ini", added=[(2, "commands = pytest || true")])), root=tmp_path) == ["runner-neutered"]


def test_package_json_noop_test_scripts():
    for value in ["exit 0", "true", ":", "echo skipped"]:
        assert rules(cs(fc("package.json", added=[(5, f'    "test": "{value}",')]))) == ["runner-neutered"], value
    assert rules(cs(fc("package.json", added=[(5, '    "test:unit": "vitest || true",')]))) == ["runner-neutered"]
