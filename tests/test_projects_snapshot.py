import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from all_tomorrow import projects_snapshot as ps
from all_tomorrow.console.projects import SnapshotStore
from all_tomorrow.web import Auth, create_app


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
    app = create_app(auth=Auth("owner", "pw", "s" * 32), collector_token="collector", console_data_dir=str(tmp_path))
    snap = {"collected_at": "2026-10-19T00:00:00+00:00", "projects": [{"id": "p", "name": "P"}]}
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/internal/projects", json=snap).status_code == 401
        assert client.post("/internal/projects", json=snap, headers={"authorization": "Bearer nope"}).status_code == 401
        assert client.post("/internal/projects", json=snap, headers={"authorization": "Bearer collector"}).status_code == 204
        big = {"projects": [{"id": "x" * 1_100_000}]}
        assert client.post("/internal/projects", content=json.dumps(big),
                           headers={"authorization": "Bearer collector"}).status_code == 413
        assert client.post("/internal/projects", content=b"{not json",
                           headers={"authorization": "Bearer collector"}).status_code == 422
        assert client.post("/internal/projects", json={"projects": "nope"},
                           headers={"authorization": "Bearer collector"}).status_code == 422
        assert client.get("/api/project-snapshot").status_code == 401
        client.post("/api/login", json={"username": "owner", "password": "pw"})
        assert client.get("/api/project-snapshot").json()["projects"][0]["id"] == "p"
        etag = client.get("/api/project-snapshot").headers["etag"]
        assert client.get("/api/project-snapshot", headers={"if-none-match": etag}).status_code == 304
        assert "AT.pages[\"/project/\"]" in client.get("/static/console/pages/projects.js").text
    # The rejected pushes did not replace the stored copy, and it survives a restart.
    assert json.loads(SnapshotStore(tmp_path / "projects" / "projects-snapshot.json").body)["projects"][0]["name"] == "P"


def test_snapshot_read_is_null_before_first_push(tmp_path) -> None:
    app = create_app(auth=Auth("owner", "pw", "s" * 32), collector_token="collector", console_data_dir=str(tmp_path))
    with TestClient(app, base_url="https://testserver") as client:
        client.post("/api/login", json={"username": "owner", "password": "pw"})
        response = client.get("/api/project-snapshot")
        assert response.status_code == 200 and response.json() is None


def test_collector_push_token_prefers_collector_env(monkeypatch) -> None:
    from all_tomorrow.usage import collector_token

    monkeypatch.delenv("ALL_TOMORROW_COLLECTOR_TOKEN", raising=False)
    monkeypatch.setenv("ALL_TOMORROW_USAGE_TOKEN", "legacy")
    assert collector_token("ALL_TOMORROW_COLLECTOR_TOKEN") == "legacy"
    monkeypatch.setenv("ALL_TOMORROW_COLLECTOR_TOKEN", "new")
    assert collector_token("ALL_TOMORROW_COLLECTOR_TOKEN") == "new"
    assert collector_token("SOME_OTHER_ENV") is None


def test_every_plugin_has_a_panel_script() -> None:
    from all_tomorrow.project_panels import plugins

    panels = Path(ps.__file__).parent / "static" / "panels"
    assert sorted(plugins()) == sorted(p.stem for p in panels.glob("*.js"))
