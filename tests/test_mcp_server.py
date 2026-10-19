import json

import pytest

from all_tomorrow import mcp_server


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "PROJECTS_PATH", tmp_path / "projects.json")
    monkeypatch.setattr(mcp_server, "RUNS_DIR", tmp_path / "runs")
    workers = tmp_path / "workers.json"
    workers.write_text(json.dumps({"allowed_roots": [tmp_path.as_posix()], "workers": {}}))
    monkeypatch.setattr(mcp_server, "WORKERS_PATH", workers)
    return tmp_path


def test_registered_project_is_listed_and_added_to_worker_roots(registry) -> None:
    project = registry / "other"
    project.mkdir()
    mcp_server.register_project("other", str(project), notes="game")
    assert mcp_server.list_projects()[0]["project_id"] == "other"
    assert project.as_posix() in mcp_server._worker_config()["allowed_roots"]
    assert mcp_server.project_status("other")["path"] == project.as_posix()
    with pytest.raises(ValueError):
        mcp_server.project_status("missing")


def test_run_status_comes_from_run_files(registry) -> None:
    run = registry / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"run_id": "r1", "project_id": "p", "pid": 999999}))
    (run / "result.json").write_text("")
    assert mcp_server.read_run(run)["status"] == "INTERRUPTED"
    (run / "result.json").write_text(json.dumps({"status": "SUCCESS", "payload": {"output": "ok"}}))
    assert mcp_server.get_run("r1")["result"]["payload"]["output"] == "ok"
