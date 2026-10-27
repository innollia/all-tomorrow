import pytest


@pytest.fixture(autouse=True)
def _no_real_knowhow(tmp_path, monkeypatch):
    """register_project seeds know-how from .artifacts/knowhow; tests must not read the real one (or call Jev)."""
    monkeypatch.setenv("ALL_TOMORROW_KNOWHOW_DIR", str(tmp_path / "no-knowhow"))
