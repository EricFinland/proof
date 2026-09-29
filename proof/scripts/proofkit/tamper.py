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
_TEST_SUBJECT = re.compile(r"^\s*(?:async\s+)?def\s+test_?(\w+)|^\s*func\s+Test_?(\w+)")
_SKIP = re.compile(
    r"\bpytest\.mark\.(?:skip|xfail)\b|\bpytest\.(?:skip|xfail)\s*\("
    r"|@unittest\.(?:skip|expectedFailure)\b|\bunittest\.skip\s*\(|\bself\.skipTest\s*\("
    r"|\b(?:it|describe|test|context)\.skip(?:\.\w+)?\s*\(|\bx(?:it|describe|test)\s*\("
    r"|\bthis\.skip\s*\(|\btest\.fixme\s*\("
    r"|\bt\.Skip(?:f|Now)?\s*\(|#\[ignore\b")
_PYTEST_SKIP_CALL = re.compile(r"\bpytest\.skip\s*\(")
_GO_SKIP = re.compile(r"\bt\.Skip(?:f|Now)?\s*\(")
_ONLY = re.compile(r"\b(?:it|describe|test|context)\.only\s*\(")
_FOCUS_JS = re.compile(r"(?<![\w.])f(?:it|describe)\s*\(\s*['\"`]")
_JS_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_ASSERT = re.compile(
    r"^\s*assert\b|\bassert\w*\s*\(|\bexpect\s*\(|\bself\.assert\w+\s*\("
    r"|\b(?:t|require|assert)\.(?:Error|Fatal|Equal|NotEqual|True|False|Nil|NotNil|NoError|Contains)\w*\s*\("
    r"|\bassert(?:_eq|_ne)?!\s*\(|\braises\s*\(|\.toThrow\w*\s*\(|\bassert\.throws\s*\(")
_TRIVIAL = re.compile(
    r"^\s*assert\s+(?:True|1)\s*(?:#.*)?$|expect\(\s*true\s*\)\.toBe\(\s*true\s*\)"
    r"|assert\.ok\(\s*true\s*\)|self\.assertTrue\(\s*True\s*\)|^\s*assert!\(\s*true\s*\)")
_NEUTER = re.compile(r"\|\|\s*true\b|(?:^|[;&|\s])exit\s+0\b")
_PASS_NO_TESTS = re.compile(r"--passWithNoTests")
_RUNNER = re.compile(
    r"\b(?:pytest|py\.test|jest|vitest|mocha|tox|nox)\b|\bgo\s+test\b|\bcargo\s+test\b"
    r"|\b(?:npm|yarn|pnpm|bun)\s+(?:run\s+)?test\b|\bpython\s+-m\s+(?:pytest|unittest)\b")
_PKG_SCRIPT = re.compile(r'^\s*"(test(?::[^"]*)?)"\s*:\s*"((?:[^"\\]|\\.)*)"')
_NOOP_ECHO_FAILS = re.compile(r"&&|\bexit\s+[1-9]")
_ADDOPTS = re.compile(r"^\s*addopts\s*=")
_PYTEST_SEL = re.compile(r"--deselect\b|(?:^|[\s\"'])-k[\s=]")
_PYTEST_IGNORE = re.compile(r"--ignore(?:-glob)?(?:=|\s+)(\S+)")
_PYTEST_SECTIONS = {"pytest", "tool:pytest", "tool.pytest.ini_options"}
_SECTION_HEADER = re.compile(r"^\s*\[([^\]\n]+)\]\s*$")
_MAKE_TARGET = re.compile(r"^([A-Za-z0-9_.\-/ ]+):(?!=)")
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
    return is_test_path(f.path)


def _rust_src(f):
    return f.path.endswith(".rs") and not is_test_path(f.path)


def _skippable(f):
    """Files where skips and removed tests count: test files and Rust sources."""
    return _testish(f) or _rust_src(f)


def _code(lines):
    return [(n, t) for n, t in lines if not is_comment_line(t)]


def _lines(files, attr):
    """(file, lineno, text) triples of non-comment lines, in file-then-line order."""
    return [(f, n, t) for f in files for n, t in _code(getattr(f, attr))]


def _pool_excess(gained, lost):
    """The entries of `gained` not offset by `lost`, matched by count across all files.
    Entries whose text does not appear on the other side are reported first."""
    excess = len(gained) - len(lost)
    if excess <= 0:
        return []
    other = {t.strip() for _, _, t in lost}
    fresh = [g for g in gained if g[2].strip() not in other]
    stale = [g for g in gained if g[2].strip() in other]
    return (fresh + stale)[:excess]


def _stem(path):
    name = PurePosixPath(path).name
    for pat in _STEMS:
        m = re.match(pat, name)
        if m:
            return m.group(1)
    return None


def _moved(f, changes):
    """True when the deleted test file reappears elsewhere (moved, renamed, or split)."""
    live = [g for g in changes.files if g.status != "D" and _testish(g)]
    name = PurePosixPath(f.path).name
    if any(g.status == "A" and PurePosixPath(g.path).name == name for g in live):
        return True
    defs = {t.strip() for _, t in _code(f.removed) if _TEST_DEF.search(t)}
    return bool(defs & {t.strip() for g in live for _, t in g.added})


def _deleted(changes):
    gone_src = set()
    for f in changes.files:
        if f.status == "D" and not is_test_path(f.path):
            gone_src.add(PurePosixPath(f.path).stem)
            gone_src.add(PurePosixPath(f.path).parent.name)
    out = []
    for f in changes.files:
        if f.status != "D" or not is_test_path(f.path):
            continue
        stem = _stem(f.path)
        has_defs = any(_TEST_DEF.search(t) for _, t in _code(f.removed))
        if stem is None and not has_defs:
            continue
        if _moved(f, changes) or (stem or PurePosixPath(f.path).stem) in gone_src:
            continue
        out.append(Finding("test-file-deleted", f.path, 0, f.path))
    return out


def _feature_removed(test_line, source_removed):
    m = _TEST_SUBJECT.match(test_line)
    name = (m.group(1) or m.group(2)) if m else None
    if not name:
        return False
    rx = re.compile(r"\b" + re.escape(name) + r"\b", re.I)
    return any(rx.search(t) for t in source_removed)


def _removed_tests(changes):
    """Returns (findings, paths of files that lost test definitions)."""
    files = [f for f in changes.files if f.status != "D" and _skippable(f)]

    def defs(attr):
        return [x for x in _lines(files, attr) if _TEST_DEF.search(x[2])]

    gone = _pool_excess(defs("removed"), defs("added"))
    source_removed = [t for f in changes.files if not is_test_path(f.path) for _, t in f.removed]
    findings = [Finding("test-removed", f.path, n, t) for f, n, t in gone
                if not _feature_removed(t, source_removed)]
    return findings, {f.path for f, _, _ in gone}


def _skip_lines(f, lines):
    """Skip markers among (lineno, text) lines of one file, honoring the scope exclusions."""
    by_no = dict(lines)
    conftest = PurePosixPath(f.path).name == "conftest.py"
    out = []
    for n, t in lines:
        probe = _PYTEST_SKIP_CALL.sub("", t) if conftest else t
        if not _SKIP.search(probe):
            continue
        if _GO_SKIP.search(t) and "testing.Short()" in t + by_no.get(n - 1, ""):
            continue
        out.append((f, n, t))
    return out


def _skip_rule(changes):
    files = [f for f in changes.files if _skippable(f)]
    added = [x for f in files for x in _skip_lines(f, _code(f.added))]
    removed = [x for f in files for x in _skip_lines(f, _code(f.removed))]
    return [Finding("skip-added", f.path, n, t) for f, n, t in _pool_excess(added, removed)]


def _only_lines(f, lines):
    focus = f.path.endswith(_JS_EXT)
    return [(f, n, t) for n, t in lines
            if _ONLY.search(t) or (focus and _FOCUS_JS.search(t))]


def _only_rule(changes):
    files = [f for f in changes.files if _testish(f)]
    added = [x for f in files for x in _only_lines(f, _code(f.added))]
    removed = [x for f in files for x in _only_lines(f, _code(f.removed))]
    return [Finding("only-added", f.path, n, t) for f, n, t in _pool_excess(added, removed)]


def _gutted(changes, removal_paths):
    files = [f for f in changes.files if f.status != "D" and _testish(f)]
    out = [Finding("assert-gutted", f.path, n, t) for f, n, t in _lines(files, "added")
           if _TRIVIAL.search(t)]
    removed = [x for x in _lines(files, "removed")
               if _ASSERT.search(x[2]) and x[0].path not in removal_paths]
    added = [x for x in _lines(files, "added")
             if _ASSERT.search(x[2]) and not _TRIVIAL.search(x[2])]
    return out + [Finding("assert-gutted", f.path, n, t) for f, n, t in _pool_excess(removed, added)]


def _nearest(root, path, lineno, rx):
    """Group 1 of the closest line at or above `lineno` in the file on disk matching `rx`."""
    try:
        lines = (Path(root) / path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    for i in range(min(lineno, len(lines)) - 1, -1, -1):
        m = rx.match(lines[i])
        if m:
            return m.group(1).strip()
    return ""


def _neutered_line(t):
    return bool((_NEUTER.search(t) or _PASS_NO_TESTS.search(t)) and _RUNNER.search(t))


def _package_hit(t):
    m = _PKG_SCRIPT.match(t)
    if not m:
        return False
    key, value = m.group(1), m.group(2).strip()
    if key == "test":
        noop = value in ("exit 0", "true", ":") or (
            value.startswith("echo") and not _NOOP_ECHO_FAILS.search(value))
        if noop or (_RUNNER.search(value) and _PASS_NO_TESTS.search(value)):
            return True
    return bool(_RUNNER.search(value) and _NEUTER.search(value))


def _make_hit(root, path, n, t):
    target = _nearest(root, path, n, _MAKE_TARGET).lower()
    return _neutered_line(t) and "test" in target and "clean" not in target


def _ignores_tests(t):
    return any(is_test_path(a) or is_test_path(a + "/")
               for a in (m.strip("\"'") for m in _PYTEST_IGNORE.findall(t)))


def _pytest_cfg_hit(root, path, n, t):
    section = _nearest(root, path, n, _SECTION_HEADER)
    if PurePosixPath(path).name == "tox.ini" and section.startswith("testenv") \
            and _NEUTER.search(t) and _RUNNER.search(t):
        return True
    if not (_ADDOPTS.match(t) or section in _PYTEST_SECTIONS):
        return False
    return bool(_PYTEST_SEL.search(t)) or _ignores_tests(t)


def _proof_toml_hit(t):
    return bool(_PROOF_TEST_KEY.search(t) and (_NEUTER.search(t) or _PROOF_NOOP.search(t)))


def _neuter_hit(root, path, n, t):
    name = PurePosixPath(path).name
    if name == "package.json":
        return _package_hit(t)
    if name == "Makefile" or name.endswith(".mk"):
        return _make_hit(root, path, n, t)
    if name in _PYTEST_CFG:
        return _pytest_cfg_hit(root, path, n, t)
    if path.startswith(".github/workflows/") and name.endswith((".yml", ".yaml")):
        return _neutered_line(t)
    return name == ".proof.toml" and _proof_toml_hit(t)


def _neutered(changes, root):
    root = changes.root or root
    return [Finding("runner-neutered", f.path, n, t) for f in changes.files
            for n, t in _code(f.added) if _neuter_hit(root, f.path, n, t)]


def analyze(changes, root, cfg):
    if changes is None or cfg_get(cfg, "tamper", "enabled", default=True) is False:
        return []
    disabled = set(cfg_get(cfg, "tamper", "disable", default=[]) or [])
    removed, removal_paths = _removed_tests(changes)
    by_rule = {
        "test-file-deleted": _deleted(changes),
        "test-removed": removed,
        "skip-added": _skip_rule(changes),
        "only-added": _only_rule(changes),
        "assert-gutted": _gutted(changes, removal_paths),
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
