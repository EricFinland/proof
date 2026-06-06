from proofkit.runners import detect_test_cmd, detect_build_cmd

def test_detects_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    assert detect_test_cmd(tmp_path)[0] in ("python", "pytest")

def test_detects_npm(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"jest","build":"tsc"}}')
    assert "test" in detect_test_cmd(tmp_path)
    assert "build" in detect_build_cmd(tmp_path)

def test_none_when_unknown(tmp_path):
    assert detect_test_cmd(tmp_path) is None
