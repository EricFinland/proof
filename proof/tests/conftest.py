import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_proof_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PROOF_HOME", str(tmp_path / "_proof_home"))


class GitRepo:
    def __init__(self, path):
        self.path = Path(path)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.path, capture_output=True,
                              text=True, check=True).stdout

    def write(self, rel, text):
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def delete(self, rel):
        (self.path / rel).unlink()

    def commit(self, msg="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()


@pytest.fixture
def git_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    r = GitRepo(root)
    r.git("init", "-q")
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false"),
                 ("core.autocrlf", "false")):
        r.git("config", k, v)
    return r
