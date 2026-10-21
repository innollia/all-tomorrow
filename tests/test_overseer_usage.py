import asyncio
import json
from pathlib import Path

import pytest

from all_tomorrow import usage


def test_live_codex_rpc_handshake_and_cleanup(monkeypatch):
    writes = []

    class Input:
        def write(self, data): writes.append(json.loads(data))
        async def drain(self): pass

    class Output:
        def __init__(self):
            self.lines = iter([{"id": 0, "result": {}}, {"method": "notification"},
                              {"id": 1, "result": {"rateLimits": {"primary": {"usedPercent": 7}}}}])
        async def readline(self): return (json.dumps(next(self.lines)) + "\n").encode()

    class Process:
        stdin, stdout, returncode = Input(), Output(), None
        def kill(self): self.returncode = -1
        async def wait(self): return self.returncode

    process = Process()
    async def spawn(*args, **kwargs): return process
    monkeypatch.setattr("all_tomorrow.local_workers.discover_executable", lambda _: "codex.exe")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    result = asyncio.run(usage.codex_live_limits())
    assert result["primary"]["usedPercent"] == 7
    assert [w["method"] for w in writes] == ["initialize", "initialized", "account/rateLimits/read"]
    assert process.returncode == -1


def test_codex_logs_use_observation_time_instead_of_syncthing_mtime(tmp_path):
    import os
    for name, date, percent in [("new.jsonl", "2026-10-21T00:00:00Z", 3),
                                ("synced-old.jsonl", "2026-10-17T00:00:00Z", 70)]:
        path = tmp_path / name
        path.write_text(json.dumps({"timestamp": date, "payload": {"rate_limits": {
            "primary": {"used_percent": percent}}}}), encoding="utf-8")
    os.utime(tmp_path / "synced-old.jsonl", (2_000_000_000, 2_000_000_000))
    assert usage.latest_codex_rate_limits(tmp_path)[0]["primary"]["used_percent"] == 3


def test_claude_refresh_keeps_other_credentials_and_never_reports_values(tmp_path, monkeypatch):
    path = tmp_path / ".claude/.credentials.json"
    path.parent.mkdir()
    oauth = {"accessToken": "expired-secret", "refreshToken": "refresh-secret", "expiresAt": 1}
    path.write_text(json.dumps({"claudeAiOauth": oauth, "other": {"kept": True}}), encoding="utf-8")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({"access_token": "new-secret", "refresh_token": "rotated-secret", "expires_in": 3600}).encode()

    monkeypatch.setattr(usage.urllib.request, "urlopen", lambda *a, **kw: Response())
    refreshed = usage.refresh_claude(tmp_path, oauth)
    assert refreshed["accessToken"] == "new-secret" and refreshed["refreshToken"] == "rotated-secret"
    assert json.loads(path.read_text())["other"] == {"kept": True}
    assert not list(path.parent.glob(".usage-refresh-*"))


def test_claude_refresh_does_not_overwrite_a_new_cli_login(tmp_path, monkeypatch):
    path = tmp_path / ".claude/.credentials.json"
    path.parent.mkdir()
    old = {"accessToken": "old", "refreshToken": "old-refresh", "expiresAt": 1}
    fresh_cli = {"accessToken": "CLI-new", "refreshToken": "CLI-refresh", "expiresAt": 2}
    path.write_text(json.dumps({"claudeAiOauth": old}), encoding="utf-8")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self):
            path.write_text(json.dumps({"claudeAiOauth": fresh_cli}), encoding="utf-8")
            return b'{"access_token":"refresh-new","expires_in":3600}'

    monkeypatch.setattr(usage.urllib.request, "urlopen", lambda *a, **kw: Response())
    assert usage.refresh_claude(tmp_path, old) == fresh_cli


def test_missing_project_directory_is_skipped_by_worker_inventory(tmp_path, monkeypatch):
    from all_tomorrow import mcp_server
    config = tmp_path / "workers.json"
    config.write_text(json.dumps({"allowed_roots": [str(tmp_path)], "workers": {"codex": {}}}))
    monkeypatch.setattr(mcp_server, "WORKERS_PATH", config)
    monkeypatch.setattr(mcp_server, "load_projects", lambda: {"missing": {"path": str(tmp_path / "absent")}})
    assert mcp_server._worker_config()["allowed_roots"] == [str(tmp_path)]


def test_blank_pool_value_can_be_filled_without_restarting_reporter(tmp_path, monkeypatch):
    from all_tomorrow.overseer.environment import load_key_pool
    name = "ALL_TOMORROW_TEST_LATE_SECRET"
    monkeypatch.delenv(name, raising=False)
    path = tmp_path / "pool.env"
    path.write_text(name + "=\n", encoding="utf-8")
    load_key_pool(path)
    path.write_text(name + "=test-only-value\n", encoding="utf-8")
    load_key_pool(path)
    import os
    assert os.environ[name] == "test-only-value"
    monkeypatch.delenv(name)
