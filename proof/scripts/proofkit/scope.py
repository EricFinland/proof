"""Check that change claims match what actually changed."""
import re
from pathlib import Path

from proofkit.classifier import is_change_claim, is_fix_claim
from proofkit.findings import Finding, is_comment_line, suspect_result

_DOC = re.compile(r"\.(?:md|rst|adoc)$|^docs?/|(^|/)(?:README|CHANGELOG|LICENSE)[^/]*$", re.I)
_IGNORED = re.compile(r"(^|/)(?:\.proof\.toml|proof-report\.md)$|(^|/)\.proof/")
_VERB = re.compile(r"\b(?:added|created|implemented|wrote|introduced)\b", re.I)
_FIRST_PERSON_FIX = re.compile(r"\bi(?:['’]ve|\s+have)?\s+fixed\b", re.I)
_TICK = re.compile(r"`([^`\s]{2,120})`")
_IDENT = re.compile(r"^[A-Za-z_][\w.]*(?:\(\))?$")
_VERSION = re.compile(r"^v?\d+(?:\.\d+)+$")
_ABSOLUTE = re.compile(r"^(?:/|[A-Za-z]:/)")
_EXTS = {"py", "js", "ts", "tsx", "jsx", "mjs", "cjs", "go", "rs", "java", "kt", "rb", "php",
         "cs", "c", "h", "cpp", "hpp", "md", "json", "toml", "yaml", "yml", "css", "scss",
         "html", "sh", "sql", "swift", "vue", "svelte",
         "txt", "ini", "cfg", "lock", "xml", "gradle", "kts", "env", "conf", "mk", "proto",
         "graphql", "ipynb"}
_MAX_READ = 2_000_000


def _ext(tok):
    if tok.endswith(("/", "()")):
        return ""
    base = tok.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def _basename(path):
    return path.rsplit("/", 1)[-1]


def _lacks_extension(path):
    base = _basename(path)
    return base.startswith(".") or "." not in base


def named_items(msg, changed=()):
    """Return (paths, symbols) named in backticks in sentences that claim an addition."""
    known = set(changed) | {_basename(c) for c in changed}
    paths, syms = [], []
    for sent in re.split(r"(?<=[.!?])\s+|\n", msg or ""):
        if not _VERB.search(sent):
            continue
        for tok in _TICK.findall(sent):
            t = tok.replace("\\", "/")
            if "://" in t or _ABSOLUTE.match(t) or _VERSION.match(t) or _IGNORED.search(t):
                continue
            if (_ext(t) in _EXTS or t.startswith(("./", "../")) or t.endswith("/")
                    or t in known):
                p = re.sub(r"^(?:\.{1,2}/)+", "", t)
                if p and p not in paths:
                    paths.append(p)
            elif "/" in t:
                continue
            elif _IDENT.match(t):
                s = t.removesuffix("()").split(".")[-1]
                if s not in syms:
                    syms.append(s)
    return paths, syms


def _disk_text(base, path):
    try:
        data = (base / path).read_bytes()[:_MAX_READ]
    except (OSError, ValueError):
        return ""
    if b"\0" in data[:8192]:
        return ""
    return data.decode("utf-8", "ignore")


def _path_changed(p, changed):
    if p.endswith("/"):
        return any(c.startswith(p) or ("/" + p) in c for c in changed)
    return any(c == p or c.endswith("/" + p) for c in changed)


def analyze(msg, changes, root=""):
    if changes is None or changes.approximate or not is_change_claim(msg):
        return []
    files = [f for f in changes.files if not _IGNORED.search(f.path)]
    changed = [f.path for f in files]
    paths, syms = named_items(msg, changed)
    if not files:
        if _FIRST_PERSON_FIX.search(msg) or paths or syms:
            return [Finding("empty-change", "", 0, "no files changed since the baseline")]
        return []
    out = []
    code = [f for f in files if not _DOC.search(f.path)]
    lineless = [f for f in code if not (f.added or f.removed)]  # binary or mode-only changes are real
    plain = any(_lacks_extension(f.path) for f in code)  # Makefile, Dockerfile, dotfiles
    docs_only = not code or (not plain and not lineless and all(
        is_comment_line(t) for f in code for _, t in f.added + f.removed))
    names_code = bool(syms) or any(not _DOC.search(p) for p in paths)
    if docs_only and (is_fix_claim(msg) or names_code):
        out.append(Finding("docs-only", files[0].path, 0, "only documentation or comments changed"))
    for p in paths:
        if not _path_changed(p, changed):
            out.append(Finding("named-path-unchanged", p, 0, f"claimed a change to {p}, but it is unchanged"))
    lines = "\n".join(t for f in files for _, t in f.added + f.removed)
    base = changes.root or root
    disk = None
    for s in syms:
        rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(s) + r"(?![A-Za-z0-9])")
        if rx.search(lines) or s in {_basename(c) for c in changed}:
            continue
        if disk is None:
            disk = "\n".join(_disk_text(Path(base), c) for c in changed) if base else ""
        if not rx.search(disk):
            out.append(Finding("named-symbol-missing", "", 0, f"claimed {s}, but it appears nowhere in the change"))
    return out


def to_result(claim, findings):
    if not findings:
        return None
    return suspect_result(claim, "scope", "claim does not match the diff: "
                          + ", ".join(sorted({f.rule for f in findings})), findings,
                          command="git diff (baseline)")
