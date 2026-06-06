from pathlib import Path
SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"

def test_skill_has_frontmatter():
    txt = SKILL.read_text(encoding="utf-8")
    assert txt.startswith("---")
    assert "name:" in txt and "description:" in txt

def test_skill_mentions_arm_and_verify():
    txt = SKILL.read_text(encoding="utf-8").lower()
    assert "proof.py arm" in txt and "verify" in txt
