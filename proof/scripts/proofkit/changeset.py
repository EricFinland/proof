"""What changed between a baseline commit and the current working tree."""
import re
from dataclasses import dataclass, field

from proofkit import gitutil

_ARTIFACT = re.compile(r"(^|/)proof-report\.md$|(^|/)\.proof/|(^|/)__pycache__/|\.pyc$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class FileChange:
    path: str
    status: str
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)


@dataclass
class ChangeSet:
    base_commit: str
    approximate: bool
    files: list

    def paths(self):
        return [f.path for f in self.files]

    def get(self, path):
        return next((f for f in self.files if f.path == path), None)

    def is_empty(self):
        return not self.files


_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, "\\": 92, '"': 34}


def _unquote(v):
    """Decode git's C-quoted path form; plain values lose only git's trailing tab."""
    if not (len(v) >= 2 and v[0] == '"'):
        return v[:-1] if v.endswith("\t") else v
    end = v.rfind('"')
    body, out, i = v[1:end], bytearray(), 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n in _ESCAPES:
                out.append(_ESCAPES[n])
                i += 2
                continue
            if n in "01234567":
                j = i + 1
                while j < len(body) and j < i + 4 and body[j] in "01234567":
                    j += 1
                out.append(int(body[i + 1:j], 8) & 0xFF)
                i = j
                continue
        out += c.encode("utf-8")
        i += 1
    return out.decode("utf-8", errors="replace")


def _strip_prefix(p):
    p = _unquote(p)
    return p[2:] if p[:2] in ("a/", "b/") else p


def _parse(diff, files):
    cur, in_header, old_path = None, False, ""
    old_no = new_no = 0
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            cur, in_header = None, True
            continue
        if in_header:
            if line.startswith("--- "):
                old_path = _strip_prefix(line[4:])
            elif line.startswith("+++ "):
                p = line[4:]
                cur = files.get(old_path if p == "/dev/null" else _strip_prefix(p))
            m = _HUNK.match(line)
            if m:
                in_header = False
                old_no, new_no = int(m.group(1)), int(m.group(2))
            continue
        m = _HUNK.match(line)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(2))
            continue
        if cur is None or line.startswith("\\"):
            continue
        if line.startswith("+"):
            cur.added.append((new_no, line[1:]))
            new_no += 1
        elif line.startswith("-"):
            cur.removed.append((old_no, line[1:]))
            old_no += 1


def compute(root, base):
    cur_tree = gitutil.snapshot_tree(root)
    base_tree = gitutil.rev_parse(root, f"{base.commit}^{{tree}}")
    files = {}
    parts = gitutil.git(root, "diff", "--name-status", "-z", "--no-renames",
                        base_tree, cur_tree).split("\0")
    for i in range(0, len(parts) - 1, 2):
        status, path = parts[i], parts[i + 1]
        if status and path and not _ARTIFACT.search(path):
            files[path] = FileChange(path, status[0])
    _parse(gitutil.git(root, "diff", "-U0", "--no-color", "--no-renames", "--no-ext-diff",
                       base_tree, cur_tree), files)
    return ChangeSet(base.commit, base.approximate, sorted(files.values(), key=lambda f: f.path))


def for_claim(root, session=None, since=None, marker_root=None):
    try:
        from proofkit.baseline import resolve
        b = resolve(root, session=session, since=since, marker_root=marker_root)
        return compute(b.root, b) if b else None
    except Exception:
        return None
