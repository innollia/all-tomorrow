import json

from fastapi.testclient import TestClient

from all_tomorrow.console.usage import UsageStore
from all_tomorrow.web import Auth, create_app

SNAPSHOT = {
    "collected_at": "2026-10-19T00:00:00+00:00",
    "providers": [{"id": "claude", "name": "Claude", "plan": "Max 20x", "status": "connected",
                   "observed_at": "2026-10-19T00:00:00+00:00",
                   "windows": [{"label": "5-hour", "percent": 3, "resets_at": "2026-10-19T03:00:00+00:00"}]}],
}


def test_usage_ingest_requires_collector_token_and_is_shown_after_login(tmp_path) -> None:
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32, edge_token="edge-secret"),
                     collector_token="collector-secret", console_data_dir=str(tmp_path))
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/internal/usage", json=SNAPSHOT).status_code == 401
        assert client.post("/internal/usage", json=SNAPSHOT, headers={"authorization": "Bearer edge-secret"}).status_code == 401
        # A bad token is refused before the body is validated.
        assert client.post("/internal/usage", json={"junk": 1}, headers={"authorization": "Bearer nope"}).status_code == 401
        assert client.post("/internal/usage", json={"junk": 1},
                           headers={"authorization": "Bearer collector-secret"}).status_code == 422
        assert client.post("/internal/usage", json=SNAPSHOT,
                           headers={"authorization": "Bearer collector-secret"}).status_code == 204
        assert client.get("/api/usage").status_code == 401
        client.post("/api/login", json={"username": "owner", "password": "correct horse"})
        assert client.get("/api/usage").json()["providers"][0]["windows"][0]["percent"] == 3
        failed = {**SNAPSHOT, "providers": [{**SNAPSHOT["providers"][0], "status": "error", "error": "refresh:http_403"}]}
        assert client.post("/internal/usage", json=failed,
                           headers={"authorization": "Bearer collector-secret"}).status_code == 204
        assert client.get("/api/usage").json()["providers"][0]["error"] == "refresh:http_403"
        assert "/static/console/pages/usage.js" in client.get("/").text
        assert 'AT.pages["/usage"]' in client.get("/static/console/pages/usage.js").text
    assert UsageStore(tmp_path / "usage" / "usage.json").snapshot["providers"][0]["plan"] == "Max 20x"


def test_usage_ingest_is_off_without_a_collector_token(tmp_path) -> None:
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path))
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/internal/usage", json=SNAPSHOT, headers={"authorization": "Bearer x"})
        assert response.status_code == 503
        client.post("/api/login", json={"username": "owner", "password": "correct horse"})
        assert client.get("/api/usage").json() is None


def test_claude_limits_map_to_dashboard_windows() -> None:
    from all_tomorrow.usage import claude_windows

    windows = claude_windows({"limits": [
        {"kind": "session", "percent": 3, "resets_at": "a"},
        {"kind": "weekly_all", "percent": 97, "resets_at": "b"},
        {"kind": "weekly_scoped", "percent": 1, "resets_at": "c", "scope": {"model": {"display_name": "Fable"}}},
    ]})
    assert [w["label"] for w in windows] == ["5-hour", "Weekly", "Weekly · Fable"]
    older = claude_windows({"five_hour": {"utilization": 12, "resets_at": 0}})
    assert older == [{"label": "5-hour", "percent": 12.0, "resets_at": "1970-01-01T00:00:00+00:00"}]


def test_codex_limits_come_from_the_newest_session_log(tmp_path) -> None:
    from all_tomorrow.usage import collect_codex

    codex = tmp_path / ".codex"
    (codex / "sessions" / "2026").mkdir(parents=True)
    claims = json.dumps({"https://api.openai.com/auth": {"chatgpt_plan_type": "pro"}}).encode()
    import base64

    payload = base64.urlsafe_b64encode(claims).decode().rstrip("=")
    (codex / "auth.json").write_text(json.dumps({"tokens": {"id_token": f"h.{payload}.s"}}), encoding="utf-8")
    event = {"timestamp": "2026-10-19T01:00:00Z", "payload": {"rate_limits": {
        "primary": {"used_percent": 40, "window_minutes": 300, "resets_at": 1_800_000_000},
        "secondary": {"used_percent": 9, "window_minutes": 10080, "resets_at": 1_800_100_000}}}}
    (codex / "sessions" / "2026" / "s.jsonl").write_text("not json\n" + json.dumps(event) + "\n", encoding="utf-8")

    entry = collect_codex(tmp_path)
    assert entry["status"] == "connected" and entry["plan"] == "Pro"
    assert [(w["label"], w["percent"]) for w in entry["windows"]] == [("5-hour", 40.0), ("Weekly", 9.0)]
    assert entry["observed_at"] == "2026-10-19T01:00:00Z"


def test_missing_logins_are_reported_not_raised(tmp_path) -> None:
    from all_tomorrow.usage import collect

    snapshot = collect(tmp_path)
    assert [p["status"] for p in snapshot["providers"]] == ["not_logged_in", "not_logged_in"]
