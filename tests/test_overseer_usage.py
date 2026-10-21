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


@pytest.mark.parametrize("phase", ["refresh", "usage"])
@pytest.mark.parametrize("code,body,status,reason", [
    (403, b"error code: 1010 secret", "error", "http_403"),
    (400, b'{"error":"invalid_grant","description":"secret"}', "needs_login", "http_400:invalid_grant"),
    (401, b'{"error":{"type":"invalid_token"}}', "needs_login", "http_401:invalid_token"),
    (429, b"secret", "error", "http_429"),
    (500, b'{"error":"invalid_grant"}', "error", "http_500"),
    (None, b"", "error", "URLError"),
])
def test_claude_failures_only_request_login_for_auth_rejection(tmp_path, monkeypatch, phase, code, body, status, reason):
    import io
    import urllib.error
    path = tmp_path / ".claude/.credentials.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "secret", "refreshToken": "secret",
                                               "expiresAt": 1 if phase == "refresh" else 9999999999999}}))
    def fail(request, **kwargs):
        assert request.get_header("User-agent") == usage.CLAUDE_USER_AGENT
        if code is None:
            raise urllib.error.URLError("secret")
        raise urllib.error.HTTPError(request.full_url, code, "secret", {}, io.BytesIO(body))
    monkeypatch.setattr(usage.urllib.request, "urlopen", fail)
    result = usage.collect_claude(tmp_path)
    assert result["status"] == status
    assert result["error"] == phase + ":" + reason
    assert "secret" not in json.dumps(result)


def test_claude_refresh_and_usage_send_user_agent(tmp_path, monkeypatch):
    path = tmp_path / ".claude/.credentials.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "old", "refreshToken": "refresh", "expiresAt": 1}}))
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return (b'{"access_token":"fresh","expires_in":3600}' if len(requests) == 1
                    else b'{"five_hour":{"utilization":7}}')
    def open_request(request, **kwargs):
        requests.append(request)
        assert request.get_header("User-agent") == usage.CLAUDE_USER_AGENT
        return Response()
    monkeypatch.setattr(usage.urllib.request, "urlopen", open_request)
    result = usage.collect_claude(tmp_path)
    assert result["status"] == "connected" and result["windows"][0]["percent"] == 7
    assert len(requests) == 2


def test_claude_missing_refresh_token_requires_login(tmp_path):
    path = tmp_path / ".claude/.credentials.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "secret", "expiresAt": 1}}))
    result = usage.collect_claude(tmp_path)
    assert result["status"] == "needs_login"
    assert result["error"] == "refresh:missing_refresh_token"


def test_unreadable_claude_credentials_do_not_request_login(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError("secret")
    monkeypatch.setattr(Path, "read_text", fail)
    result = usage.collect_claude(tmp_path)
    assert result["status"] == "error"
    assert result["error"] == "credentials:PermissionError"
