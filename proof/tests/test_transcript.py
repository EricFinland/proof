# proof/tests/test_transcript.py
import json
from proofkit.transcript import last_assistant_text

def test_reads_last_assistant_message(tmp_path):
    f = tmp_path / "t.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "do it"}},
        {"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "text", "text": "All done, tests pass."}]}},
    ]
    f.write_text("\n".join(json.dumps(l) for l in lines))
    assert "tests pass" in last_assistant_text(str(f))

def test_missing_file_returns_empty():
    assert last_assistant_text("/nope/none.jsonl") == ""
