"""Real Claude Code transcript feature extractor for proofml.

Parses a Claude Code session .jsonl (one JSON entry per line) and derives the
behavioral signals proofml cares about per session:

  - ran_test_cmd: a Bash tool_use ran a recognized test/check runner before the
    final success claim.
  - claimed_without_running: the final assistant claim asserts success but no
    qualifying test command ran.
  - diff_lines: total changed-line estimate across Edit / Write / MultiEdit
    tool_use blocks (newline count of the written content).
  - touched_test_files: any edited / written file path matches a test pattern.
  - hedged / absolute: from the final claim text.

The claim string is the last assistant text (mirrors proof's
transcript.last_assistant_text). Parsing is robust to malformed lines and to
message.content being either a string or a list of blocks.

Labeling: if a ledger is supplied we try to attach a real label by matching
project plus nearest timestamp. We do NOT fabricate labels. When no ledger
match exists the row is emitted UNLABELED (a feature dict with no "label" key)
so it can be used for shadow-mode inference rather than training.

CLI:
    python -m proofml.extract --transcript session.jsonl \\
        [--ledger ledger.jsonl] --out data/real.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from proofml.data import load_ledger
from proofml.schema import Example


# --------------------------------------------------------------------------
# Claim-text signals. The claim regexes follow proof's extractor.py so that the
# notion of "a success claim" stays consistent across the two codebases.
# --------------------------------------------------------------------------

# A success claim is any assertion that tests pass / build is green / it is done.
_SUCCESS_CLAIM_RE = re.compile(
    r"\btests?\s+(?:are\s+)?pass"
    r"|\ball\s+tests?\s+pass"
    r"|\bbuild\s+is\s+(?:clean|green|passing)\b"
    r"|\bbuilds?\s+success"
    r"|\bbuild\s+is\s+green\b"
    r"|\b(?:it|everything|this)\s+(?:is\s+)?(?:works|working)\b"
    r"|\ball\s+(?:checks|green)\b"
    r"|\bdone\b"
    r"|\bcomplete[d]?\b"
    r"|\bpasses?\b"
    r"|\bgreen\b",
    re.I,
)

# Hedged language: uncertainty markers around a claim.
_HEDGE_RE = re.compile(
    r"\bshould\s+(?:pass|work|be)\b"
    r"|\bi\s+think\b"
    r"|\bi\s+believe\b"
    r"|\bprobably\b"
    r"|\blikely\b"
    r"|\bmight\b"
    r"|\bmay\b"
    r"|\bseems?\s+to\b"
    r"|\bappears?\s+to\b"
    r"|\bhopefully\b"
    r"|\bin\s+theory\b",
    re.I,
)

# Absolute language: confident, unqualified assertions.
_ABSOLUTE_RE = re.compile(
    r"\ball\s+tests?\s+pass"
    r"|\beverything\s+(?:passes|works)\b"
    r"|\bdefinitely\b"
    r"|\bcertainly\b"
    r"|\bguaranteed\b"
    r"|\bfully\s+(?:working|tested|passing)\b"
    r"|\b100%\b"
    r"|\bno\s+(?:errors|failures|issues)\b"
    r"|\bdone\b"
    r"|\bcompletely\b",
    re.I,
)

# Test / check runner commands. Recognizing any of these in a Bash command marks
# ran_test_cmd True.
_TEST_CMD_RE = re.compile(
    r"\bpytest\b"
    r"|\bpy\.test\b"
    r"|\bunittest\b"
    r"|\bnpm\s+(?:run\s+)?test\b"
    r"|\bnpm\s+t\b"
    r"|\byarn\s+test\b"
    r"|\bpnpm\s+(?:run\s+)?test\b"
    r"|\bmake\s+test\b"
    r"|\bmake\s+check\b"
    r"|\bcargo\s+test\b"
    r"|\bgo\s+test\b"
    r"|\bjest\b"
    r"|\bvitest\b"
    r"|\bmocha\b"
    r"|\btox\b"
    r"|\bphpunit\b"
    r"|\brspec\b"
    r"|\bgradle\s+test\b"
    r"|\bmvn\s+test\b"
    r"|\bdotnet\s+test\b"
    r"|\bctest\b"
    r"|\bbun\s+test\b",
    re.I,
)

# Test file paths: test_*, *_test.*, *.spec.*, *.test.*, anything under /tests/.
_TEST_FILE_RE = re.compile(
    r"(^|[\\/])test_[^\\/]*"
    r"|[^\\/]*_test\.[A-Za-z0-9]+$"
    r"|[^\\/]*\.spec\.[A-Za-z0-9]+$"
    r"|[^\\/]*\.test\.[A-Za-z0-9]+$"
    r"|[\\/]tests?[\\/]"
    r"|(^|[\\/])tests?[\\/]",
    re.I,
)

# Tool names that represent a code change.
_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def is_success_claim(text: str) -> bool:
    """True if the claim text asserts success (tests pass / done / build green)."""
    return bool(_SUCCESS_CLAIM_RE.search(text or ""))


def is_hedged(text: str) -> bool:
    return bool(_HEDGE_RE.search(text or ""))


def is_absolute(text: str) -> bool:
    return bool(_ABSOLUTE_RE.search(text or ""))


def is_test_command(command: str) -> bool:
    return bool(_TEST_CMD_RE.search(command or ""))


def is_test_file(path: str) -> bool:
    return bool(_TEST_FILE_RE.search(path or ""))


# --------------------------------------------------------------------------
# Transcript parsing.
# --------------------------------------------------------------------------

def _iter_entries(transcript_path: str) -> List[dict]:
    """Read a .jsonl transcript into a list of dict entries, robustly.

    Malformed (non-JSON) lines and non-dict JSON values are skipped silently.
    """
    p = Path(transcript_path)
    if not p.is_file():
        return []
    entries: List[dict] = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries


def _content_blocks(entry: dict) -> List[Any]:
    """Return message.content as a list, handling string-vs-list content.

    A string content becomes a single synthetic text block so downstream code
    can iterate uniformly.
    """
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content", "")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    return []


def _entry_role(entry: dict) -> str:
    """Best-effort role for an entry (assistant / user / etc.)."""
    msg = entry.get("message")
    if isinstance(msg, dict):
        role = msg.get("role")
        if role:
            return str(role)
    return str(entry.get("type") or "")


def _text_of(entry: dict) -> str:
    """Concatenate text blocks from an entry's content (string or list)."""
    parts: List[str] = []
    for block in _content_blocks(entry):
        if isinstance(block, dict) and block.get("type") == "text":
            txt = block.get("text", "")
            if isinstance(txt, str):
                parts.append(txt)
    return " ".join(p for p in parts if p)


def last_assistant_text(transcript_path: str) -> str:
    """Last non-empty assistant text in the transcript (proof-compatible)."""
    last = ""
    for entry in _iter_entries(transcript_path):
        if _entry_role(entry) == "assistant":
            txt = _text_of(entry)
            if txt.strip():
                last = txt
    return last


def _newline_count(value: Any) -> int:
    """Estimate changed lines from a written string.

    A single trailing newline is ignored so "a\\nb\\n" counts as 2 lines, not 3.
    A non-empty string with no trailing newline still counts as at least 1 line.
    """
    if not isinstance(value, str) or not value:
        return 0
    body = value[:-1] if value.endswith("\n") else value
    if not body:
        return 0
    return body.count("\n") + 1


def _tool_uses(entries: List[dict]) -> List[Dict[str, Any]]:
    """Flatten all tool_use blocks across assistant entries, in order."""
    uses: List[Dict[str, Any]] = []
    for entry in entries:
        for block in _content_blocks(entry):
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            uses.append(block)
    return uses


def _diff_from_edit_input(name: str, inp: dict) -> int:
    """Estimate changed lines from one Edit/Write/MultiEdit tool input."""
    if not isinstance(inp, dict):
        return 0
    total = 0
    # Write: content. Edit: new_string. MultiEdit: edits[].new_string.
    if "content" in inp:
        total += _newline_count(inp.get("content"))
    if "new_string" in inp:
        total += _newline_count(inp.get("new_string"))
    edits = inp.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict):
                total += _newline_count(e.get("new_string"))
    return total


def _file_paths_from_edit_input(inp: dict) -> List[str]:
    """All file paths referenced by an edit/write tool input."""
    if not isinstance(inp, dict):
        return []
    paths: List[str] = []
    for key in ("file_path", "path", "notebook_path", "filename"):
        v = inp.get(key)
        if isinstance(v, str) and v:
            paths.append(v)
    return paths


def extract_features(transcript_path: str) -> Dict[str, Any]:
    """Parse one transcript into a behavioral feature dict (no label).

    Returns a dict shaped like asdict(Example) minus the label:
        claim, project, ts, source, ran_test_cmd, claimed_without_running,
        diff_lines, touched_test_files, hedged, absolute
    project and ts are left blank/0.0 here; the labeling step fills/uses ledger
    info. This is the UNLABELED inference row.
    """
    entries = _iter_entries(transcript_path)
    claim = last_assistant_text(transcript_path)

    ran_test_cmd = False
    diff_lines = 0
    touched_test_files = False

    for use in _tool_uses(entries):
        name = use.get("name")
        inp = use.get("input")
        if name == "Bash" and isinstance(inp, dict):
            cmd = inp.get("command", "")
            if is_test_command(cmd):
                ran_test_cmd = True
        if name in _EDIT_TOOLS:
            diff_lines += _diff_from_edit_input(name, inp if isinstance(inp, dict) else {})
            for fp in _file_paths_from_edit_input(inp if isinstance(inp, dict) else {}):
                if is_test_file(fp):
                    touched_test_files = True

    claimed_success = is_success_claim(claim)
    claimed_without_running = bool(claimed_success and not ran_test_cmd)

    return {
        "claim": claim,
        "project": "",
        "ts": 0.0,
        "source": "transcript",
        "ran_test_cmd": ran_test_cmd,
        "claimed_without_running": claimed_without_running,
        "diff_lines": int(diff_lines),
        "touched_test_files": touched_test_files,
        "hedged": is_hedged(claim),
        "absolute": is_absolute(claim),
    }


# --------------------------------------------------------------------------
# Ledger labeling (no fabrication).
# --------------------------------------------------------------------------

def match_ledger_label(
    feat: Dict[str, Any],
    ledger: List[Example],
    project: Optional[str] = None,
    ts: Optional[float] = None,
    max_ts_delta: float = float("inf"),
) -> Optional[int]:
    """Try to attach a real label from the ledger by project + nearest ts.

    Matching strategy:
      1. Restrict to ledger rows whose project matches (when a project is given).
      2. Among the candidates whose claim text equals the transcript claim, or
         (failing that) all candidates, pick the one with the nearest timestamp.
      3. Return its label. Return None when there is no usable match, so the row
         stays UNLABELED. We never invent a label.

    project / ts come from CLI flags or future enrichment. If neither narrows the
    field and there is exactly one ledger row, that row's label is used.
    """
    if not ledger:
        return None

    candidates = ledger
    if project:
        proj_matches = [e for e in ledger if e.project == project]
        if proj_matches:
            candidates = proj_matches
        else:
            # A project was specified but the ledger has nothing for it: no match.
            return None

    claim_text = (feat.get("claim") or "").strip()
    exact = [e for e in candidates if (e.claim or "").strip() == claim_text]
    pool = exact if exact else candidates

    if ts is not None:
        scored = [(abs(float(e.ts) - float(ts)), e) for e in pool]
        scored.sort(key=lambda t: t[0])
        delta, best = scored[0]
        if delta > max_ts_delta:
            return None
        return int(best.label)

    # No timestamp to disambiguate. Only trust an unambiguous match.
    if exact:
        labels = {int(e.label) for e in exact}
        if len(labels) == 1:
            return labels.pop()
        return None
    if len(pool) == 1:
        return int(pool[0].label)
    return None


# --------------------------------------------------------------------------
# Output.
# --------------------------------------------------------------------------

def build_rows(
    transcript_path: str,
    ledger_path: Optional[str] = None,
    project: Optional[str] = None,
    ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Produce output rows for one transcript.

    Returns a list with a single row dict. The row has a "label" key only when a
    real ledger match was found; otherwise the key is omitted (unlabeled).
    """
    feat = extract_features(transcript_path)
    if project:
        feat["project"] = project
    if ts is not None:
        feat["ts"] = float(ts)

    label: Optional[int] = None
    if ledger_path:
        ledger = load_ledger(ledger_path)
        label = match_ledger_label(feat, ledger, project=project, ts=ts)

    if label is not None:
        # A labeled row round-trips through Example so it matches the interchange
        # format exactly (asdict(Example)).
        ex = Example(
            claim=feat["claim"],
            label=int(label),
            project=feat["project"],
            ts=float(feat["ts"]),
            source="transcript",
            ran_test_cmd=feat["ran_test_cmd"],
            claimed_without_running=feat["claimed_without_running"],
            diff_lines=feat["diff_lines"],
            touched_test_files=feat["touched_test_files"],
            hedged=feat["hedged"],
            absolute=feat["absolute"],
        )
        return [asdict(ex)]

    # Unlabeled: emit the feature dict WITHOUT a label key. No fabrication.
    return [feat]


def write_rows(rows: List[Dict[str, Any]], path: str) -> str:
    """Write rows as JSONL (one JSON object per line). Creates parent dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return str(p)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m proofml.extract",
        description="Extract proofml behavioral features from a Claude Code "
        "session .jsonl transcript.",
    )
    parser.add_argument(
        "--transcript",
        required=True,
        help="Path to a Claude Code session .jsonl transcript.",
    )
    parser.add_argument(
        "--ledger",
        default=None,
        help="Optional proof ledger.jsonl to attach a real label by project + "
        "nearest timestamp. Without it (or without a match), rows are unlabeled.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project name for ledger matching and to stamp on the row.",
    )
    parser.add_argument(
        "--ts",
        type=float,
        default=None,
        help="Timestamp for nearest-ts ledger matching.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSONL path.",
    )
    args = parser.parse_args(argv)

    rows = build_rows(
        args.transcript,
        ledger_path=args.ledger,
        project=args.project,
        ts=args.ts,
    )
    out = write_rows(rows, args.out)

    labeled = sum(1 for r in rows if "label" in r)
    unlabeled = len(rows) - labeled
    print(f"wrote {len(rows)} row(s) to {out}")
    print(f"  labeled (ledger match):   {labeled}")
    print(f"  unlabeled (shadow mode):  {unlabeled}")
    for r in rows:
        tag = "label=%s" % r["label"] if "label" in r else "label=<none>"
        print(
            "  - %s claimed_without_running=%s ran_test_cmd=%s "
            "diff_lines=%s touched_test_files=%s"
            % (
                tag,
                r.get("claimed_without_running"),
                r.get("ran_test_cmd"),
                r.get("diff_lines"),
                r.get("touched_test_files"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
