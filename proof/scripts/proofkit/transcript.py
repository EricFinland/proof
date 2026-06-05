# proof/scripts/proofkit/transcript.py
import json
from pathlib import Path

def _text_of(entry: dict) -> str:
    msg = entry.get("message", {})
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""

def last_assistant_text(transcript_path: str) -> str:
    p = Path(transcript_path)
    if not p.is_file():
        return ""
    last = ""
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = entry.get("message", {}).get("role") or entry.get("type")
        if role == "assistant":
            txt = _text_of(entry)
            if txt.strip():
                last = txt
    return last
