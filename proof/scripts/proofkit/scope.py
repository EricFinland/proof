"""Check that change claims match what actually changed."""
import re

from proofkit.classifier import is_change_claim
from proofkit.findings import Finding, is_comment_line, suspect_result

_DOC = re.compile(r"\.(?:md|rst|txt|adoc)$|(^|/)docs?/|(^|/)(?:README|CHANGELOG|LICENSE)[^/]*$", re.I)
_IGNORED = re.compile(r"(^|/)\.proof\.toml$")
_VERB = re.compile(r"\b(?:added|created|implemented|wrote|introduced)\b", re.I)
_TICK = re.compile(r"`([^`\s]{2,120})`")
_IDENT = re.compile(r"^[A-Za-z_][\w.]*(?:\(\))?$")
_EXTS = {"py", "js", "ts", "tsx", "jsx", "mjs", "cjs", "go", "rs", "java", "kt", "rb", "php",
         "cs", "c", "h", "cpp", "hpp", "md", "json", "toml", "yaml", "yml", "css", "scss",
         "html", "sh", "sql", "swift", "vue", "svelte"}


def _is_path(tok):
    if "/" in tok:
        return True
    ext = tok.rsplit(".", 1)[-1].lower() if "." in tok else ""
    return ext in _EXTS and not tok.endswith("()")


def named_items(msg):
    paths, syms = [], []
    for sent in re.split(r"(?<=[.!?])\s+|\n", msg or ""):
        if not _VERB.search(sent):
            continue
        for tok in _TICK.findall(sent):
            if _is_path(tok):
                p = tok[2:] if tok.startswith("./") else tok
                if p not in paths:
                    paths.append(p)
            elif _IDENT.match(tok):
                s = tok.removesuffix("()").split(".")[-1]
                if s not in syms:
                    syms.append(s)
    return paths, syms


def analyze(msg, changes):
    if changes is None or changes.approximate or not is_change_claim(msg):
        return []
    files = [f for f in changes.files if not _IGNORED.search(f.path)]
    if not files:
        return [Finding("empty-change", "", 0, "no files changed since the session started")]
    out = []
    code = [f for f in files if not _DOC.search(f.path)]
    lineless = [f for f in code if not (f.added or f.removed)]  # binary or mode-only changes are real
    if not code or (not lineless and all(is_comment_line(t) for f in code
                                         for _, t in f.added + f.removed)):
        out.append(Finding("docs-only", files[0].path, 0, "only documentation or comments changed"))
    paths, syms = named_items(msg)
    changed = [f.path for f in files]
    for p in paths:
        if not any(c == p or c.endswith("/" + p) for c in changed):
            out.append(Finding("named-path-unchanged", p, 0, f"claimed a change to {p}, but it is unchanged"))
    added = [t for f in files for _, t in f.added]
    for s in syms:
        rx = re.compile(r"\b" + re.escape(s) + r"\b")
        if not any(rx.search(t) for t in added):
            out.append(Finding("named-symbol-missing", "", 0, f"claimed {s}, but no added line contains it"))
    return out


def to_result(claim, findings):
    if not findings:
        return None
    return suspect_result(claim, "scope", "claim does not match the diff: "
                          + ", ".join(sorted({f.rule for f in findings})), findings,
                          command="git diff (baseline)")
