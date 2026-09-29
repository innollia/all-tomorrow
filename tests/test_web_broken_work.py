"""Feature 6 -- broken/stuck Work: list, retry (via RepairService, audited),
clean up (abandon, audited). Never a blind automatic retry."""
import asyncio

from fastapi.testclient import TestClient

from all_tomorrow.domain.ids import new_event_id, new_goal_id, new_run_id, new_work_id
from all_tomorrow.domain.state import GoalRecord, RunRecord, RunStatus, WorkRecord, WorkStatus
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore, SemanticEvent
from all_tomorrow.web import Auth, create_app
from all_tomorrow.web_control import WebControl

SECRET = "s" * 40


def _evt(**kw):
    kw.setdefault("actor", "t")
    kw.setdefault("type", "e")
    return SemanticEvent(event_id=new_event_id(), **kw)


def _client(control: WebControl) -> TestClient:
    app = create_app(auth=Auth("admin", "pw", SECRET), cookie_secure=False, control=control)
    client = TestClient(app)
    assert client.post("/api/login", json={"username": "admin", "password": "pw"}).status_code == 204
    return client


async def _seed_failed_work(store, *, user="admin"):
    g = GoalRecord(goal_id=new_goal_id(), user_id=user, title="목표")
    await store.create_goal(g, _evt(goal_id=g.goal_id))
    w = WorkRecord(work_id=new_work_id(), goal_id=g.goal_id, title="실패할 일")
    await store.create_work(w, _evt(work_id=w.work_id))
    await store.transition_work_status(w.work_id, WorkStatus.RUNNING, w.revision, _evt(work_id=w.work_id))
    running = await store.get_work(w.work_id)
    await store.transition_work_status(
        w.work_id, WorkStatus.FAILED, running.revision, _evt(work_id=w.work_id, type="work.failed"),
    )
    return g, w


def test_list_broken_work_shows_failed_work():
    store = InMemoryGoalWorkRunStore()
    g, w = asyncio.run(_seed_failed_work(store))
    client = _client(WebControl(store))
    listing = client.get("/api/broken-work").json()
    assert len(listing) == 1
    assert listing[0]["work_id"] == str(w.work_id)
    assert listing[0]["status"] == "FAILED"


def test_retry_broken_work_creates_new_work_under_same_goal():
    store = InMemoryGoalWorkRunStore()
    g, w = asyncio.run(_seed_failed_work(store))
    client = _client(WebControl(store))
    result = client.post(f"/api/broken-work/{w.work_id}/retry").json()
    assert result["original_work_id"] == str(w.work_id)
    new_work_id_ = result["new_work_id"]
    assert new_work_id_ != str(w.work_id)

    all_work = asyncio.run(store.list_work(g.goal_id))
    assert len(all_work) == 2
    new_work = [x for x in all_work if str(x.work_id) == new_work_id_][0]
    assert new_work.status == WorkStatus.PENDING
    # the original FAILED Work is untouched -- provenance preserved
    original = [x for x in all_work if str(x.work_id) == str(w.work_id)][0]
    assert original.status == WorkStatus.FAILED


def test_clean_up_broken_work_is_audited_and_never_retries():
    store = InMemoryGoalWorkRunStore()
    g, w = asyncio.run(_seed_failed_work(store))
    control = WebControl(store)
    client = _client(control)
    result = client.post(f"/api/broken-work/{w.work_id}/clean-up").json()
    assert result["status"] == "ABANDONED"

    # audited on the shared RepairService -- no blind retry happened
    audit = control.repair_service.audit_trail()
    assert any(entry.action == "abandon" and entry.operator == "admin" for entry in audit)
    assert not any(entry.action == "retry" for entry in audit)
    # the Work itself never went back to PENDING (no second run created)
    all_work = asyncio.run(store.list_work(g.goal_id))
    assert len(all_work) == 1


def test_broken_work_of_other_user_is_not_visible():
    store = InMemoryGoalWorkRunStore()
    _, w = asyncio.run(_seed_failed_work(store, user="alice"))
    client = _client(WebControl(store))  # logged in as admin
    assert client.get("/api/broken-work").json() == []
    assert client.post(f"/api/broken-work/{w.work_id}/retry").status_code == 404
    assert client.post(f"/api/broken-work/{w.work_id}/clean-up").status_code == 404
