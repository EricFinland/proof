"""Tests for the 6 code-review fixes.

FIX 1: _split_serve always uses POSIX mode (no quote retention on Windows).
FIX 2: _is_local recognizes IPv6, 0.0.0.0, bracketed IPv6, and is case-insensitive.
FIX 3: boot Popen uses DEVNULL for stdout (regression: existing boot tests green).
FIX 4: DIRECTIVE quotes {script} with double quotes.
FIX 5: marker _save is atomic (write -> tmp -> replace; result is valid JSON).
FIX 6: proof.py verify --out-dir writes report to that directory; trigger directive contains --out-dir.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# FIX 1: _split_serve helper
# ---------------------------------------------------------------------------

def test_split_serve_strips_quotes_from_spaced_path():
    """A quoted path with a space must yield a token WITHOUT surrounding quotes."""
    from proofkit.strategies.http import _split_serve
    result = _split_serve('"/path with spaces/python" app.py 8000')
    # The first token must not contain quote characters
    assert result[0] == "/path with spaces/python"
    assert result[1] == "app.py"
    assert result[2] == "8000"


def test_split_serve_simple_command():
    from proofkit.strategies.http import _split_serve
    result = _split_serve("python app.py 3000")
    assert result == ["python", "app.py", "3000"]


def test_split_serve_quoted_arg_no_extra_quotes():
    """Quoted arg should become a token without quotes, not double-quoted."""
    from proofkit.strategies.http import _split_serve
    result = _split_serve('node "dist/server.js"')
    assert result == ["node", "dist/server.js"]


# ---------------------------------------------------------------------------
# FIX 2: _is_local recognizes IPv6, 0.0.0.0, UPPERCASE localhost
# ---------------------------------------------------------------------------

def test_is_local_localhost():
    from proofkit.strategies.http import _is_local
    assert _is_local("http://localhost:3000/") is True


def test_is_local_127():
    from proofkit.strategies.http import _is_local
    assert _is_local("http://127.0.0.1:8080/") is True


def test_is_local_ipv6_bracketed():
    from proofkit.strategies.http import _is_local
    assert _is_local("http://[::1]:3000/") is True


def test_is_local_ipv6_short():
    from proofkit.strategies.http import _is_local
    # urlsplit handles http://[::1]:3000 correctly
    assert _is_local("http://[::1]:3000") is True


def test_is_local_0000():
    from proofkit.strategies.http import _is_local
    assert _is_local("http://0.0.0.0:8080/") is True


def test_is_local_uppercase_localhost():
    from proofkit.strategies.http import _is_local
    assert _is_local("http://LOCALHOST:3000/") is True


def test_is_local_external_is_not_local():
    from proofkit.strategies.http import _is_local
    assert _is_local("http://example.com/") is False


def test_is_local_example_invalid():
    from proofkit.strategies.http import _is_local
    assert _is_local("http://example.invalid:9/") is False


# ---------------------------------------------------------------------------
# FIX 4: DIRECTIVE quotes script path
# ---------------------------------------------------------------------------

def test_directive_quotes_script():
    from proof_trigger import DIRECTIVE
    # Before format(), {script} should be wrapped in escaped double quotes
    assert '"{script}"' in DIRECTIVE


def test_directive_format_contains_quoted_script():
    """After formatting, the resolved script path must be surrounded by double quotes."""
    from proof_trigger import DIRECTIVE
    formatted = DIRECTIVE.format(script="/some/path/proof.py", tp="t.jsonl", cwd="/cwd", sid="s1")
    assert '"/some/path/proof.py"' in formatted


def test_directive_contains_out_dir():
    """Directive must include --out-dir flag for FIX 6."""
    from proof_trigger import DIRECTIVE
    assert "--out-dir" in DIRECTIVE


# ---------------------------------------------------------------------------
# FIX 5: marker _save is atomic (produces valid JSON, _load round-trips)
# ---------------------------------------------------------------------------

def test_save_produces_valid_json_readable_by_load(tmp_path):
    from proofkit.marker import record_attempt, record_outcome, _load
    msg = "Atomic write test."
    record_attempt("sess", msg, root=tmp_path)
    record_outcome("sess", msg, "pass", root=tmp_path)
    data = _load(tmp_path)
    # Must round-trip without error and have the right structure
    from proofkit.marker import claim_key, last_outcome
    assert last_outcome("sess", msg, root=tmp_path) == "pass"
    # The underlying file must be valid JSON (not truncated)
    store = tmp_path / "verified.json"
    loaded = json.loads(store.read_text())
    key = claim_key(msg)
    assert loaded["sess"][key]["last"] == "pass"


def test_save_no_tmp_file_left_behind(tmp_path):
    """After _save, the .tmp file must not exist."""
    from proofkit.marker import record_attempt
    record_attempt("sess", "msg", root=tmp_path)
    tmp_file = tmp_path / "verified.tmp"
    assert not tmp_file.exists()


# ---------------------------------------------------------------------------
# FIX 6: verify --out-dir writes report to specified directory
# ---------------------------------------------------------------------------

PROOF_SCRIPT = str(Path(__file__).resolve().parents[1] / "scripts" / "proof.py")
FIX_FAIL = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tests_fail"


def test_verify_out_dir_writes_report_there(tmp_path):
    """proof.py verify --out-dir <dir> must write proof-report.md into <dir>."""
    out_dir = tmp_path / "reports"
    out_dir.mkdir()
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant",
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": "All tests pass."}]},
    }))
    r = subprocess.run(
        [sys.executable, PROOF_SCRIPT, "verify",
         "--transcript", str(transcript),
         "--root", str(FIX_FAIL),
         "--out-dir", str(out_dir)],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    # Report must exist in out_dir, NOT in cwd
    assert (out_dir / "proof-report.md").exists(), (
        f"proof-report.md not found in out_dir. stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    assert not (tmp_path / "proof-report.md").exists(), (
        "proof-report.md was written to cwd instead of out_dir"
    )


def test_trigger_directive_contains_out_dir_value(tmp_path):
    """The rendered trigger directive must contain --out-dir followed by the cwd path."""
    from proof_trigger import DIRECTIVE
    cwd = "/some/project"
    rendered = DIRECTIVE.format(
        script="/scripts/proof.py",
        tp="/tmp/t.jsonl",
        cwd=cwd,
        sid="sess1",
    )
    assert f'--out-dir "{cwd}"' in rendered
