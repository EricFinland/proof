"""Per-session repository baselines, captured at SessionStart."""
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from proofkit import gitutil

REF_PREFIX = "refs/proof/baseline/"
MAX_AGE = 7 * 86400


@dataclass
class Baseline:
    root: str
    commit: str
    approximate: bool
    ts: float


def _home(marker_root=None):
    if marker_root:
        return Path(marker_root)
    env = os.environ.get("PROOF_HOME", "")
    return Path(env) if env else Path.home() / ".proof"


def _safe(session):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session or "")[:120] or "unknown"


def _record_path(session, marker_root=None):
    d = _home(marker_root) / "baselines"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_safe(session)}.json"


def load(root, session, marker_root=None):
    p = _record_path(session, marker_root)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
        if Path(rec["root"]).resolve() != Path(root).resolve():
            return None
        return Baseline(rec["root"], rec["commit"], bool(rec.get("approximate")),
                        float(rec.get("ts", 0)))
    except (OSError, ValueError, KeyError):
        return None


def capture(root, session, marker_root=None):
    try:
        if not gitutil.is_repo(root):
            return None
        top = gitutil.toplevel(root)
        existing = load(top, session, marker_root)
        if existing:
            return existing
        tree = gitutil.snapshot_tree(top)
        head = gitutil.rev_parse(top, "HEAD")
        commit = gitutil.commit_tree(top, tree, parent=head)
        gitutil.update_ref(top, REF_PREFIX + _safe(session), commit)
        rec = {"root": str(top), "commit": commit, "head": head, "ts": time.time(),
               "approximate": False}
        _record_path(session, marker_root).write_text(json.dumps(rec), encoding="utf-8")
        try:
            prune(top, marker_root)
        except Exception:
            pass
        return Baseline(str(top), commit, False, rec["ts"])
    except Exception:
        return None


def resolve(root, session=None, since=None, marker_root=None):
    try:
        if not gitutil.is_repo(root):
            return None
        top = gitutil.toplevel(root)
        if since:
            c = gitutil.rev_parse(top, f"{since}^{{commit}}")
            return Baseline(str(top), c, False, time.time()) if c else None
        if session:
            b = load(top, session, marker_root)
            if b:
                return b
        head = gitutil.rev_parse(top, "HEAD")
        return Baseline(str(top), head, True, time.time()) if head else None
    except Exception:
        return None


def prune(root, marker_root=None, now=None):
    now = now or time.time()
    out = gitutil.git(root, "for-each-ref", "--format=%(refname) %(committerdate:unix)",
                      REF_PREFIX)
    for line in out.splitlines():
        ref, _, ts = line.rpartition(" ")
        if ts.isdigit() and now - int(ts) > MAX_AGE:
            gitutil.delete_ref(root, ref)
    for f in (_home(marker_root) / "baselines").glob("*.json"):
        try:
            if now - float(json.loads(f.read_text(encoding="utf-8")).get("ts", 0)) > MAX_AGE:
                f.unlink()
        except Exception:
            pass
