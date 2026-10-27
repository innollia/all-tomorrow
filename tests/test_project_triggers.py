import asyncio
import json

from fastapi.testclient import TestClient
import pytest

from all_tomorrow.adapters.workers import ClaudeWorker
from all_tomorrow.contracts import WorkerResult, WorkerStatus
from all_tomorrow.domain.state import WorkStatus
from all_tomorrow.overseer.project_triggers import ProjectTrigger, ProjectTriggers, prompt_for
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore
from all_tomorrow.web import Auth, create_app
from all_tomorrow.web_control import WebControl


def setup(tmp_path):
    procedure = tmp_path / "SKILL.md"
    procedure.write_text("정기 처리 참고 절차", encoding="utf-8")
    definition = {"cwd": str(tmp_path), "procedure": str(procedure), "executor": "claude", "channel_id": "123"}
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"study": definition}), encoding="utf-8")
    return registry, definition


def call(i=1):
    return ProjectTrigger(project="study", channel_id="123", message_id=str(i), author_id="456")


class FakeWorker:
    worker_id = "claude"
    capabilities = frozenset({"analysis"})

    def __init__(self, gate=None, fail=False):
        self.requests = []
        self.gate, self.fail = gate, fail

    async def execute(self, request):
        self.requests.append(request)
        if self.gate:
            await self.gate.wait()
        return WorkerResult(request.request_id, request.trace_id,
                            WorkerStatus.FAILED if self.fail else WorkerStatus.SUCCESS,
                            payload={"output": "answered"}, error="fake failure" if self.fail else None)


async def drain(service):
    while service.tasks:
        await asyncio.gather(*list(service.tasks.values()))


async def test_coalesced_followup_keeps_every_message_and_work_run(tmp_path):
    registry, _ = setup(tmp_path)
    store = InMemoryGoalWorkRunStore()
    gate = asyncio.Event()
    worker = FakeWorker(gate)
    service = ProjectTriggers(store, registry_path=registry, base=tmp_path, worker_factory=lambda d: worker)
    assert not (await service.trigger(call()))["coalesced"]
    await asyncio.sleep(0)
    for i in range(2, 6):
        assert (await service.trigger(call(i)))["coalesced"]
    assert len(worker.requests) == 1
    gate.set()
    await drain(service)
    assert len(worker.requests) == 2
    assert worker.requests[0].payload["cwd"] == str(tmp_path)
    assert all(f'"message_id": "{i}"' in worker.requests[1].payload["task"] for i in range(2, 6))
    goals = await store.list_goals()
    works = [w for g in goals for w in await store.list_work(g.goal_id)]
    assert len(works) == 2 and all(w.status == WorkStatus.SUCCEEDED for w in works)
    for work in works:
        assert len(await store.list_runs(work.work_id)) == 1


async def test_limit_persisted_and_window_expires(tmp_path):
    registry, _ = setup(tmp_path)
    now = [10000]
    worker = FakeWorker()
    service = ProjectTriggers(InMemoryGoalWorkRunStore(), registry_path=registry, base=tmp_path,
                              worker_factory=lambda d: worker, clock=lambda: now[0])
    for i in range(6):
        await service.trigger(call(i))
        await drain(service)
    restarted = ProjectTriggers(service.store, registry_path=registry, base=tmp_path,
                                worker_factory=lambda d: worker, clock=lambda: now[0])
    with pytest.raises(Exception) as exc:
        await restarted.trigger(call(7))
    assert exc.value.status_code == 429
    assert len(worker.requests) == 6
    assert list((tmp_path / "reports").glob("project-trigger-limit-*.json"))
    now[0] += 3600
    await restarted.trigger(call(8))
    await drain(restarted)
    assert len(worker.requests) == 7


async def test_pending_reservation_respects_limit(tmp_path):
    registry, _ = setup(tmp_path)
    gate = asyncio.Event()
    service = ProjectTriggers(InMemoryGoalWorkRunStore(), registry_path=registry, base=tmp_path,
                              worker_factory=lambda d: FakeWorker(gate))
    for _ in range(5):
        service.reserve("study")
    await service.trigger(call())
    with pytest.raises(Exception) as exc:
        await service.trigger(call(2))
    assert exc.value.status_code == 429
    assert not service.pending
    gate.set()
    await drain(service)


async def test_worker_failure_records_failed_work_and_report(tmp_path):
    registry, _ = setup(tmp_path)
    service = ProjectTriggers(InMemoryGoalWorkRunStore(), registry_path=registry, base=tmp_path,
                              worker_factory=lambda d: FakeWorker(fail=True))
    await service.trigger(call())
    await drain(service)
    goal = (await service.store.list_goals())[0]
    assert (await service.store.list_work(goal.goal_id))[0].status == WorkStatus.FAILED
    assert list((tmp_path / "reports").glob("project-trigger-failed-*.json"))


def test_endpoint_auth_registry_and_validation(tmp_path, monkeypatch):
    registry, _ = setup(tmp_path)
    monkeypatch.setenv("ALL_TOMORROW_PROJECT_TRIGGERS", str(registry))
    monkeypatch.setenv("ALL_TOMORROW_OVERSEER_DIR", str(tmp_path))
    app = create_app(auth=Auth("owner", "password", "s" * 32, edge_token="edge-test"),
                     control=WebControl(InMemoryGoalWorkRunStore()))
    app.state.project_triggers.worker_factory = lambda d: FakeWorker()
    headers = {"Authorization": "Bearer edge-test"}
    with TestClient(app) as client:
        body = call().model_dump()
        assert client.post("/internal/edge/project-trigger", json=body).status_code == 401
        assert client.post("/internal/edge/project-trigger", json=body,
                           headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.post("/internal/edge/project-trigger", json={**body, "project": "unknown"}, headers=headers).status_code == 404
        assert client.post("/internal/edge/project-trigger", json={**body, "channel_id": "999"}, headers=headers).status_code == 403
        assert client.post("/internal/edge/project-trigger", json={**body, "message_id": "bad"}, headers=headers).status_code == 422
        response = client.post("/internal/edge/project-trigger", json=body, headers=headers)
        assert response.status_code == 202 and response.json()["accepted"]
        registry.write_text("broken", encoding="utf-8")
        assert client.post("/internal/edge/project-trigger", json=body, headers=headers).status_code == 503


def test_prompt_and_claude_cli_contract(tmp_path):
    _, definition = setup(tmp_path)
    prompt = prompt_for("study", definition, [call()])
    for text in ["단순 질문", "기록·계획 수정", "--to", "mark", "@멘션", "직전 몇 개", "message_id", "정기 실행이 아니라"]:
        assert text in prompt
    worker = ClaudeWorker(allowed_roots=(str(tmp_path),))
    argv = worker.build_argv(prompt)
    assert argv[-2:] == ["--", prompt]
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert "--strict-mcp-config" not in argv and "--setting-sources" not in argv and "--allowedTools" not in argv
    assert "Bash(git push:*)" in argv[argv.index("--disallowedTools") + 1]
    assert worker.parse_output('{"type":"result","subtype":"success","result":"OK"}')["output"] == "OK"
    with pytest.raises(RuntimeError):
        worker.parse_output('{"type":"result","subtype":"error_during_execution","is_error":true}')


def test_worker_mode_prompt_uses_project_instructions(tmp_path):
    from all_tomorrow.overseer.project_triggers import prompt_for
    proc = tmp_path / "CLAUDE.md"
    proc.write_text("게임 지침", encoding="utf-8")
    class Call:
        def model_dump(self):
            return {"project": "pai-games", "message_id": "9"}
    text = prompt_for("pai-games", {"procedure": str(proc), "mode": "worker", "channel_id": "1"}, [Call()])
    assert "게임 지침" in text and "discord_thread.py" not in text
