import json
import os
import sys

import pytest
from fastmcp import Client

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


def test_dispatch_runs_worker_cli_in_project_and_records_result(registry, monkeypatch) -> None:
    # Fake Codex CLI: proves the run reaches the project cwd through local_workers' CLI contract.
    events = [{"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
              {"type": "turn.completed"}]
    cli = registry / "fake_codex.py"
    cli.write_text("from pathlib import Path\nPath('proof.txt').write_text('written')\n"
                   f"print({chr(10).join(map(json.dumps, events))!r})\n", encoding="utf-8")
    (registry / "workers.json").write_text(json.dumps({
        "allowed_roots": [registry.as_posix()],
        "workers": {"codex": {"argv": [sys.executable, str(cli)]}}}))
    project = registry / "proj"
    project.mkdir()
    mcp_server.register_project("proj", str(project))

    def run_inline(run_dir):  # the detached spawn itself is Windows/WMI-specific; run the child here
        mcp_server._run_child(run_dir)
        return os.getpid(), "inline"

    monkeypatch.setattr(mcp_server, "_spawn_detached", run_inline)
    started = mcp_server.dispatch_task("proj", "codex", "write proof")
    run = mcp_server.get_run(started["run_id"])
    assert run["status"] == "SUCCESS", run
    assert run["result"]["payload"]["output"] == "done"
    assert (project / "proof.txt").read_text() == "written"
    assert [r["run_id"] for r in mcp_server.list_runs("proj")] == [started["run_id"]]
    with pytest.raises(ValueError):
        mcp_server.dispatch_task("proj", "unknown", "task")


def test_subscription_usage_reports_missing_usage_module(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, mcp_server.USAGE_MODULE, None)
    with pytest.raises(RuntimeError, match="not available"):
        mcp_server.subscription_usage()


async def test_server_exposes_the_control_tools() -> None:
    async with Client(mcp_server.mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == {"list_projects", "register_project", "project_status", "list_local_workers",
                     "dispatch_task", "get_run", "list_runs", "subscription_usage"}
