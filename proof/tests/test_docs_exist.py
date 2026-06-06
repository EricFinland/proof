from pathlib import Path
REF = Path(__file__).resolve().parents[1] / "references"

def test_subagent_prompt_has_adversarial_rule():
    txt = (REF / "verifier-subagent.md").read_text().lower()
    assert "assume" in txt and "false" in txt
    assert "proof.py verify" in txt

def test_hook_setup_documents_recursion_guard():
    txt = (REF / "hook-setup.md").read_text().lower()
    assert "stop_hook_active" in txt
