"""Tests for M12.2: .claude-plugin/plugin.json manifest."""
import json
import re
from pathlib import Path

# Repo root is two levels up from this test file (proof/tests -> proof -> repo root)
REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / ".claude-plugin" / "plugin.json"
SKILL_MD = REPO_ROOT / "proof" / "SKILL.md"


def _load_manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _skill_description():
    text = SKILL_MD.read_text(encoding="utf-8")
    m = re.search(r'^description:\s*(.+)$', text, re.MULTILINE)
    assert m, "Could not find description in SKILL.md front matter"
    return m.group(1).strip()


def test_manifest_exists():
    assert MANIFEST_PATH.exists(), f"Missing: {MANIFEST_PATH}"


def test_manifest_parses_as_json():
    data = _load_manifest()
    assert isinstance(data, dict)


def test_manifest_name():
    data = _load_manifest()
    assert data["name"] == "proof"


def test_manifest_version_matches_proofkit():
    import sys
    sys.path.insert(0, str(REPO_ROOT / "proof" / "scripts"))
    import proofkit
    data = _load_manifest()
    assert data["version"] == proofkit.__version__, (
        f"plugin.json version {data['version']!r} != "
        f"proofkit.__version__ {proofkit.__version__!r}"
    )


def test_manifest_description_nonempty():
    data = _load_manifest()
    assert "description" in data
    assert isinstance(data["description"], str)
    assert len(data["description"]) > 10


def test_manifest_description_matches_skill_md():
    data = _load_manifest()
    expected = _skill_description()
    assert data["description"] == expected, (
        f"plugin.json description does not match SKILL.md front matter.\n"
        f"  plugin.json: {data['description']!r}\n"
        f"  SKILL.md:    {expected!r}"
    )
