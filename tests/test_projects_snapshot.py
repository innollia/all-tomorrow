import json
import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient

from all_tomorrow import projects_snapshot as ps
from all_tomorrow.web import Auth, WebState, create_app


def test_status_table_reads_first_status_column(tmp_path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "roadmap.md").write_text(
        "# R\n\n| Stage | 상태 | 비고 |\n|---|---|---|\n| [A](a.md) | 개발중 | x |\n| B | 개발완료 | y |\n\ntext\n",
        encoding="utf-8")
    assert ps.status_table(tmp_path) == [{"item": "A", "status": "개발중"}, {"item": "B", "status": "개발완료"}]


def test_repo_without_readable_head_is_flagged_without_status(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    facts = ps.git_facts(tmp_path)
    assert facts["problem"] and facts["dirty_files"] is None


def test_broken_or_oversized_plugin_does_not_drop_the_project(tmp_path) -> None:
    broken = SimpleNamespace(collect=lambda path: 1 / 0)
    huge = SimpleNamespace(collect=lambda path: {"x": "a" * (ps.PANEL_MAX_BYTES + 1)})
    item = ps.collect_project("p", {"path": str(tmp_path)}, {"p": broken})
    assert item["panel"] == {"error": "ZeroDivisionError"} and item["exists"]
    assert "size cap" in ps.collect_project("p", {"path": str(tmp_path)}, {"p": huge})["panel"]["error"]


def test_snapshot_ingest_needs_collector_token_and_login_to_read(tmp_path) -> None:
    state = WebState(project_snapshot_path=tmp_path / "snap.json")
    app = create_app(auth=Auth("owner", "pw", "s" * 32, usage_token="collector"), web_state=state)
    snap = {"collected_at": "2026-10-19T00:00:00+00:00", "projects": [{"id": "p", "name": "P"}]}
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/internal/projects", json=snap).status_code == 401
        assert client.post("/internal/projects", json=snap, headers={"authorization": "Bearer collector"}).status_code == 204
        big = {"projects": [{"id": "x" * 1_100_000}]}
        assert client.post("/internal/projects", content=json.dumps(big),
                           headers={"authorization": "Bearer collector"}).status_code == 413
        assert client.get("/api/project-snapshot").status_code == 401
        client.post("/api/login", json={"username": "owner", "password": "pw"})
        assert client.get("/api/project-snapshot").json()["projects"][0]["id"] == "p"
        etag = client.get("/api/project-snapshot").headers["etag"]
        assert client.get("/api/project-snapshot", headers={"if-none-match": etag}).status_code == 304
    assert WebState(project_snapshot_path=tmp_path / "snap.json").project_snapshot["projects"][0]["name"] == "P"
