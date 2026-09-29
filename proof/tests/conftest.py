import pytest


@pytest.fixture(autouse=True)
def _isolated_proof_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PROOF_HOME", str(tmp_path / "_proof_home"))
