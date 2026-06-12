from pathlib import Path
from proofkit.config import load_config, cfg_get


def test_missing_file_returns_empty(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg == {}


def test_valid_toml_round_trip(tmp_path):
    (tmp_path / ".proof.toml").write_text('[commands]\ntest = "pytest -q"\n', encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg_get(cfg, "commands", "test") == "pytest -q"


def test_malformed_toml_returns_empty(tmp_path):
    (tmp_path / ".proof.toml").write_text("not valid toml ][[\n", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg == {}


def test_cfg_get_default_path(tmp_path):
    cfg = {}
    assert cfg_get(cfg, "commands", "test") is None
    assert cfg_get(cfg, "commands", "test", default="fallback") == "fallback"


def test_cfg_get_nested_key(tmp_path):
    cfg = {"commands": {"build": "make build", "test": "make test"}}
    assert cfg_get(cfg, "commands", "build") == "make build"
    assert cfg_get(cfg, "missing", "key") is None
