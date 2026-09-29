"""Features 3, 4, 5 -- Run outputs (artifacts), Goal detail, and Reports, exposed
through the web control API. Uses the FastAPI TestClient against WebControl,
matching the existing tests/test_web_control.py pattern."""
import asyncio

from fastapi.testclient import TestClient

from all_tomorrow.domain.ids import new_event_id, new_goal_id, new_run_id, new_work_id
from all_tomorrow.domain.outcomes import CompletionEvidence
from all_tomorrow.domain.state import GoalRecord, RunRecord, RunStatus, WorkRecord, WorkStatus
from all_tomorrow.report.store import Report, ReportSection, ReportStatus, ReportStore
from all_tomorrow.storage.artifact_store import LocalArtifactStore
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


async def _seed_succeeded_work_with_artifact(store, artifact_store, *, user="admin"):
    g = GoalRecord(goal_id=new_goal_id(), user_id=user, title="목표")
    await store.create_goal(g, _evt(goal_id=g.goal_id))
    w = WorkRecord(work_id=new_work_id(), goal_id=g.goal_id, title="일감")
    await store.create_work(w, _evt(work_id=w.work_id))
    r = RunRecord(run_id=new_run_id(), work_id=w.work_id)
    await store.create_run(r, _evt(work_id=w.work_id, run_id=r.run_id))
    await store.transition_run_status(r.run_id, RunStatus.RUNNING, 1, _evt(run_id=r.run_id))
    await store.transition_run_status(r.run_id, RunStatus.SUCCEEDED, 2, _evt(run_id=r.run_id))
    ref = await artifact_store.store("결과물 본문", media_type="text/plain", owner_id=str(w.work_id))
    await store.transition_work_status(
        w.work_id, WorkStatus.RUNNING, w.revision, _evt(work_id=w.work_id),
    )
    work_running = await store.get_work(w.work_id)
    evidence = CompletionEvidence(
        criterion_ref="c", evaluator_ref="e", evaluator_version="1",
        artifact_refs=(ref.content_hash,),
    )
    await store.transition_work_status(
        w.work_id, WorkStatus.SUCCEEDED, work_running.revision,
        _evt(work_id=w.work_id, type="work.succeeded"), evidence=evidence,
    )
    return g, w


# --- Feature 3: artifact listing/viewing ------------------------------------
def test_list_and_view_work_artifacts(tmp_path):
    store = InMemoryGoalWorkRunStore()
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")
    g, w = asyncio.run(_seed_succeeded_work_with_artifact(store, artifact_store))
    client = _client(WebControl(store, artifact_store=artifact_store))

    listing = client.get(f"/api/works/{w.work_id}/artifacts").json()
    assert len(listing) == 1
    ref = listing[0]["artifact_id"]

    viewed = client.get(f"/api/works/{w.work_id}/artifacts/{ref}").json()
    assert viewed["content"] == "결과물 본문"


def test_artifact_of_other_users_work_is_not_visible(tmp_path):
    store = InMemoryGoalWorkRunStore()
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")
    _, w = asyncio.run(_seed_succeeded_work_with_artifact(store, artifact_store, user="alice"))
    client = _client(WebControl(store, artifact_store=artifact_store))  # logged in as "admin"

    assert client.get(f"/api/works/{w.work_id}/artifacts").status_code == 404


# --- Feature 4: Goal detail --------------------------------------------------
def test_goal_detail_shows_work_run_history_and_events(tmp_path):
    store = InMemoryGoalWorkRunStore()
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")
    g, w = asyncio.run(_seed_succeeded_work_with_artifact(store, artifact_store))
    client = _client(WebControl(store, artifact_store=artifact_store))

    detail = client.get(f"/api/goals/{g.goal_id}").json()
    assert detail["goal_id"] == str(g.goal_id)
    assert len(detail["works"]) == 1
    work = detail["works"][0]
    assert work["status"] == "SUCCEEDED"
    assert len(work["runs"]) == 1 and work["runs"][0]["status"] == "SUCCEEDED"
    assert work["artifact_refs"]
    assert any(e["type"] == "work.succeeded" for e in work["events"])


def test_goal_detail_of_other_user_is_404():
    store = InMemoryGoalWorkRunStore()
    ctl = WebControl(store)
    goal_id = asyncio.run(ctl.submit("alice", "다른 사람 일", "key-1"))["goal_id"]
    client = _client(ctl)
    assert client.get(f"/api/goals/{goal_id}").status_code == 404


# --- Feature 5: reports -------------------------------------------------------
def test_list_and_view_reports():
    store = InMemoryGoalWorkRunStore()
    report_store = ReportStore()
    report_store.upsert_draft(Report(
        report_id="rpt_1", user_id="admin", logical_period_id="2026-09-29|Asia/Seoul|bp1",
        timezone="Asia/Seoul",
        period_start_utc=__import__("datetime").datetime(2026, 9, 29, tzinfo=__import__("datetime").UTC),
        period_end_utc=__import__("datetime").datetime(2026, 9, 30, tzinfo=__import__("datetime").UTC),
        projection_version="1", input_watermark="wm1", revision=1, status=ReportStatus.DRAFT,
        summary="오늘 요약", sections=(ReportSection(title="User Work Progress", source_refs=("s1",)),),
        source_refs=("s1",),
    ))
    client = _client(WebControl(store, report_store=report_store))

    listing = client.get("/api/reports").json()
    assert len(listing) == 1 and listing[0]["report_id"] == "rpt_1"

    detail = client.get("/api/reports/rpt_1").json()
    assert detail["summary"] == "오늘 요약"
    assert detail["sections"][0]["title"] == "User Work Progress"


def test_report_of_other_user_is_404():
    import datetime as dt

    store = InMemoryGoalWorkRunStore()
    report_store = ReportStore()
    report_store.upsert_draft(Report(
        report_id="rpt_2", user_id="alice", logical_period_id="p", timezone="UTC",
        period_start_utc=dt.datetime(2026, 9, 29, tzinfo=dt.UTC), period_end_utc=dt.datetime(2026, 9, 30, tzinfo=dt.UTC),
        projection_version="1", input_watermark="wm2", revision=1, status=ReportStatus.DRAFT,
        summary="alice only", sections=(), source_refs=(),
    ))
    client = _client(WebControl(store, report_store=report_store))
    assert client.get("/api/reports/rpt_2").status_code == 404
