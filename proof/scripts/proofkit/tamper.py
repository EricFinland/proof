"""Detect tests being gamed: deleted, skipped, focused, gutted, or neutered."""
import re
from collections import Counter
from pathlib import Path, PurePosixPath

from proofkit.config import cfg_get
from proofkit.findings import Finding, is_comment_line, suspect_result

RULES = ("test-file-deleted", "test-removed", "skip-added", "only-added",
         "assert-gutted", "runner-neutered")

_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|specs?)/|(^|/)test_[^/]*\.py$|_test\.py$"
    r"|\.(test|spec)\.[cm]?[jt]sx?$|_test\.go$|(^|/)conftest\.py$")
_TEST_DEF = re.compile(
    r"^\s*(?:async\s+)?def\s+test\w*\s*\(|^\s*(?:it|test)\s*\(\s*['\"`]"
    r"|^\s*func\s+Test\w*\s*\(|^\s*#\[(?:tokio::)?test\]")
_SKIP = re.compile(
    r"@pytest\.mark\.(?:skip|skipif|xfail)\b|\bpytest\.(?:skip|xfail)\s*\("
    r"|@unittest\.skip\w*|\bunittest\.skip\w*\s*\("
    r"|\b(?:it|describe|test|context)\.(?:skip|todo)\s*\(|\bx(?:it|describe|test)\s*\("
    r"|\bt\.Skip(?:f|Now)?\s*\(|#\[ignore\b")
_ONLY = re.compile(r"\b(?:it|describe|test|context)\.only\s*\(|\bf(?:it|describe)\s*\(")
_ASSERT = re.compile(
    r"^\s*assert\b|\bassert\w*\s*\(|\bexpect\s*\(|\bself\.assert\w+\s*\("
    r"|\b(?:t|require|assert)\.(?:Error|Fatal|Equal|NotEqual|True|False|Nil|NotNil|NoError|Contains)\w*\s*\("
    r"|\bassert(?:_eq|_ne)?!\s*\(")
_TRIVIAL = re.compile(
    r"^\s*assert\s+(?:True|1)\s*(?:#.*)?$|expect\(\s*true\s*\)\.toBe\(\s*true\s*\)"
    r"|assert\.ok\(\s*true\s*\)|self\.assertTrue\(\s*True\s*\)|^\s*assert!\(\s*true\s*\)")
_NEUTER = re.compile(r"\|\|\s*true\b|--passWithNoTests|(?:^|[;&|\s])exit\s+0\b")
_PYTEST_SEL = re.compile(r"--deselect\b|--ignore(?:-glob)?[= ]|(?:^|[\s\"'])-k[\s=]")
_TEST_WORD = re.compile(r"\b(?:tests?|pytest|jest|vitest|mocha|check|ci)\b|go\s+test|cargo\s+test|npm\s+test", re.I)
_PKG_TEST_KEY = re.compile(r'"(?:pre|post)?test(?::[^"]*)?"\s*:')
_PROOF_TEST_KEY = re.compile(r"^\s*tests?\s*=")
_PROOF_NOOP = re.compile(r"""^\s*tests?\s*=\s*["'](?:true|exit 0|echo\b[^"']*|:)["']""")
_PYTEST_CFG = {"pytest.ini", "setup.cfg", "tox.ini", "pyproject.toml"}
_STEMS = (r"^test_(.+)\.py$", r"^(.+)_test\.py$", r"^(.+)\.(?:test|spec)\.[cm]?[jt]sx?$",
          r"^(.+)_test\.go$")
_LABELS = {
    "test-file-deleted": ("test file deleted", "test files deleted"),
    "test-removed": ("test removed", "tests removed"),
    "skip-added": ("skip added", "skips added"),
    "only-added": (".only added", ".only calls added"),
    "assert-gutted": ("assertion weakened", "assertions weakened"),
    "runner-neutered": ("test command altered", "test command alterations"),
}


def is_test_path(path):
    return bool(_TEST_PATH.search(path))


def _testish(f):
    return is_test_path(f.path) or f.path.endswith((".rs", "_test.go"))


def _code(lines):
    return [(n, t) for n, t in lines if not is_comment_line(t)]


def _net_added(f, rx):
    removed = Counter(t.strip() for _, t in _code(f.removed) if rx.search(t))
    out = []
    for n, t in _code(f.added):
        if rx.search(t):
            if removed[t.strip()]:
                removed[t.strip()] -= 1
            else:
                out.append((n, t))
    return out


def _stem(path):
    name = PurePosixPath(path).name
    for pat in _STEMS:
        m = re.match(pat, name)
        if m:
            return m.group(1)
    return None


def _deleted(changes):
    deleted_src = {PurePosixPath(f.path).stem for f in changes.files
                   if f.status == "D" and not is_test_path(f.path)}
    return [Finding("test-file-deleted", f.path, 0, f.path) for f in changes.files
            if f.status == "D" and is_test_path(f.path) and _stem(f.path) not in deleted_src]


def _removed_tests(changes):
    out = []
    for f in changes.files:
        if f.status == "D" or not _testish(f):
            continue
        rem = [(n, t) for n, t in _code(f.removed) if _TEST_DEF.search(t)]
        add = [(n, t) for n, t in _code(f.added) if _TEST_DEF.search(t)]
        excess = len(rem) - len(add)
        if excess > 0:
            added_text = {t.strip() for _, t in add}
            cands = [(n, t) for n, t in rem if t.strip() not in added_text]
            out += [Finding("test-removed", f.path, n, t) for n, t in cands[:excess]]
    return out


def _marker_rule(changes, rule, rx):
    return [Finding(rule, f.path, n, t) for f in changes.files if _testish(f)
            for n, t in _net_added(f, rx)]


def _gutted(changes, skip_files):
    out = []
    for f in changes.files:
        if f.status == "D" or not _testish(f):
            continue
        out += [Finding("assert-gutted", f.path, n, t) for n, t in _code(f.added)
                if _TRIVIAL.search(t)]
        if f.path in skip_files:
            continue
        rem = [(n, t) for n, t in _code(f.removed) if _ASSERT.search(t)]
        add = [(n, t) for n, t in _code(f.added) if _ASSERT.search(t) and not _TRIVIAL.search(t)]
        excess = len(rem) - len(add)
        if excess > 0:
            added_text = {t.strip() for _, t in add}
            cands = [(n, t) for n, t in rem if t.strip() not in added_text]
            out += [Finding("assert-gutted", f.path, n, t) for n, t in cands[:excess]]
    return out


def _make_target(root, path, lineno):
    try:
        lines = (Path(root) / path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    for i in range(min(lineno, len(lines)) - 1, -1, -1):
        m = re.match(r"^([A-Za-z0-9_.\-/ ]+):(?!=)", lines[i])
        if m:
            return m.group(1).strip()
    return ""


def _neutered(changes, root):
    out = []
    for f in changes.files:
        name = PurePosixPath(f.path).name
        for n, t in _code(f.added):
            hit = False
            if name == "package.json":
                hit = bool(_PKG_TEST_KEY.search(t) and _NEUTER.search(t))
            elif name == "Makefile" or name.endswith(".mk"):
                hit = bool(_NEUTER.search(t) and _TEST_WORD.search(_make_target(root, f.path, n)))
            elif name in _PYTEST_CFG:
                hit = bool(_PYTEST_SEL.search(t))
            elif f.path.startswith(".github/workflows/") and name.endswith((".yml", ".yaml")):
                hit = bool(_NEUTER.search(t) and _TEST_WORD.search(t))
            elif name == ".proof.toml":
                hit = bool(_PROOF_TEST_KEY.search(t) and (_NEUTER.search(t) or _PROOF_NOOP.search(t)))
            if hit:
                out.append(Finding("runner-neutered", f.path, n, t))
    return out


def analyze(changes, root, cfg):
    if changes is None or cfg_get(cfg, "tamper", "enabled", default=True) is False:
        return []
    disabled = set(cfg_get(cfg, "tamper", "disable", default=[]) or [])
    removed = _removed_tests(changes)
    by_rule = {
        "test-file-deleted": _deleted(changes),
        "test-removed": removed,
        "skip-added": _marker_rule(changes, "skip-added", _SKIP),
        "only-added": _marker_rule(changes, "only-added", _ONLY),
        "assert-gutted": _gutted(changes, {f.file for f in removed}),
        "runner-neutered": _neutered(changes, root),
    }
    return [f for rule in RULES if rule not in disabled for f in by_rule[rule]]


def _join(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def to_result(claim, findings):
    if not findings:
        return None
    counts = Counter(f.rule for f in findings)
    parts = [f"{counts[r]} {_LABELS[r][0 if counts[r] == 1 else 1]}" for r in RULES if counts[r]]
    return suspect_result(claim, "tamper", "possible test tampering: " + _join(parts), findings,
                          command="git diff (baseline)")
