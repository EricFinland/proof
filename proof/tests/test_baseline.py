import hashlib, json, os, subprocess, sys, time
from pathlib import Path

from proofkit import baseline, gitutil

SS = str(Path(__file__).resolve().parents[1] / "scripts" / "proof_session_start.py")


def _index_hash(repo):
    p = repo.path / ".git" / "index"
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _seed(repo):
    repo.write(".gitignore", "ignored.txt\n")
    repo.write("a.py", "x = 1\n")
    repo.commit("init")
    repo.write("untracked.py", "y = 2\n")
    repo.write("ignored.txt", "secret\n")


def test_capture_does_not_touch_index_or_status(git_repo, tmp_path):
    _seed(git_repo)
    before = (git_repo.git("status", "--porcelain"), _index_hash(git_repo))
    b = baseline.capture(git_repo.path, "sess-1", marker_root=tmp_path / "home")
    assert b and not b.approximate
    assert (git_repo.git("status", "--porcelain"), _index_hash(git_repo)) == before


def test_capture_does_not_create_index_when_absent(git_repo, tmp_path):
    git_repo.write("a.py", "x\n")
    assert _index_hash(git_repo) is None
    assert baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home") is not None
    assert _index_hash(git_repo) is None
    assert git_repo.git("status", "--porcelain").strip() == "?? a.py"


def test_capture_includes_untracked_excludes_ignored(git_repo, tmp_path):
    _seed(git_repo)
    b = baseline.capture(git_repo.path, "sess-1", marker_root=tmp_path / "home")
    names = git_repo.git("ls-tree", "-r", "--name-only", b.commit).split()
    assert "untracked.py" in names and "ignored.txt" not in names
    assert git_repo.git("rev-parse", "refs/proof/baseline/sess-1").strip() == b.commit


def test_capture_is_idempotent(git_repo, tmp_path):
    _seed(git_repo)
    a = baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    git_repo.write("later.py", "z = 3\n")
    b = baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    assert a.commit == b.commit


def test_capture_non_repo_returns_none(tmp_path):
    assert baseline.capture(tmp_path, "s", marker_root=tmp_path / "home") is None


def test_capture_repo_without_commits(git_repo, tmp_path):
    git_repo.write("a.py", "x\n")
    assert baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home") is not None


def test_resolve_fallbacks(git_repo, tmp_path):
    _seed(git_repo)
    head = git_repo.git("rev-parse", "HEAD").strip()
    r = baseline.resolve(git_repo.path, session="nope", marker_root=tmp_path / "home")
    assert r.commit == head and r.approximate
    r2 = baseline.resolve(git_repo.path, since="HEAD", marker_root=tmp_path / "home")
    assert r2.commit == head and not r2.approximate
    b = baseline.capture(git_repo.path, "s", marker_root=tmp_path / "home")
    assert baseline.resolve(git_repo.path, session="s", marker_root=tmp_path / "home").commit == b.commit


def test_prune_removes_old(git_repo, tmp_path):
    _seed(git_repo)
    baseline.capture(git_repo.path, "old", marker_root=tmp_path / "home")
    baseline.prune(git_repo.path, marker_root=tmp_path / "home", now=time.time() + 8 * 86400)
    assert "refs/proof/baseline/old" not in git_repo.git("for-each-ref")
    assert not list((tmp_path / "home" / "baselines").glob("*.json"))


def test_session_start_script_captures(git_repo, tmp_path):
    _seed(git_repo)
    env = dict(os.environ, PROOF_HOME=str(tmp_path / "home"))
    p = subprocess.run([sys.executable, SS], input=json.dumps(
        {"session_id": "ss1", "cwd": str(git_repo.path)}), capture_output=True, text=True, env=env)
    assert p.stdout == ""
    assert (tmp_path / "home" / "baselines" / "ss1.json").exists()


def test_snapshot_tree_sees_same_size_edit_in_racy_window(git_repo):
    # An entry whose mtime equals the index file's mtime is "racily clean": git
    # must re-hash it. That only works if the index copy keeps the real index mtime.
    git_repo.git("config", "core.checkStat", "minimal")
    git_repo.git("config", "core.trustctime", "false")
    f = git_repo.write("a.txt", "one\ntwo\n")
    stamp = time.time_ns() - 60 * 10**9
    os.utime(f, ns=(stamp, stamp))
    git_repo.commit("init")
    os.utime(git_repo.path / ".git" / "index", ns=(stamp, stamp))
    first = gitutil.snapshot_tree(git_repo.path)
    f.write_text("one\nTWO\n", encoding="utf-8")
    os.utime(f, ns=(stamp, stamp))
    assert (git_repo.path / ".git" / "index").stat().st_mtime_ns == stamp
    assert gitutil.snapshot_tree(git_repo.path) != first
