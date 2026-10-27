import pytest


@pytest.fixture(autouse=True)
def _no_real_knowhow(tmp_path, monkeypatch):
    """register_project seeds know-how from the oracle card DB (store.default_dir()); tests must not read
    the real overseer.sqlite or peers (or call Jev)."""
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(tmp_path / "no-overseer" / "overseer"))


@pytest.fixture(autouse=True)
def _no_real_metacog_session(monkeypatch):
    """Watchers wake a headless Claude session on blocked servers; tests must never launch a real one."""
    from all_tomorrow.overseer import metacog_session
    launched = []
    monkeypatch.setattr(metacog_session, "spawn", lambda base, fp: launched.append((base, fp)))
    return launched
