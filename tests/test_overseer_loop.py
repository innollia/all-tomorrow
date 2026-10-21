"""실제 파일·시험 프로세스와 InMemory 정본을 사용한 자기개선 고리 검증."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from all_tomorrow.domain.state import WorkStatus
from all_tomorrow.overseer import loop, metacog, reports
from all_tomorrow.overseer.schedule import wake_delay
from all_tomorrow.overseer.store import SessionStore
from all_tomorrow.overseer.workspace import ProjectChange, digest, tree
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore


@pytest.fixture(autouse=True)
def no_real_discord(monkeypatch):
    monkeypatch.setattr("all_tomorrow.overseer.environment.load_key_pool", lambda: None)
    monkeypatch.delenv("ALL_TOMORROW_DISCORD_WEBHOOK_URL", raising=False)


def project(tmp_path):
    root, base = tmp_path / "project", tmp_path / "state"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    base.mkdir()
    (root / "src/demo.py").write_text("answer = 1\n", encoding="utf-8")
    (root / "tests/test_demo.py").write_text("import demo\ndef test_answer(): assert demo.answer == 2\n", encoding="utf-8")
    return root, base, {"demo": {"path": str(root), "autonomy": {"verify_argv": ["{python}", "-m", "pytest", "-q"]}}}


def fix(**updates):
    return {"kind": "fix", "title": "계산 오류 발견", "detail": "answer가 1이라 시험 실패. 2로 고쳐 시험 통과",
            "project_id": "demo", "authority": "ordinary", "problem_key": "demo-answer-regression",
            "evidence_refs": ["project:demo"], **updates}


async def make_work(store, registry, action=None, wid="wake", limit=96):
    return await loop.materialize_actions(store, [action or fix()], wake_id=wid,
        known_refs={"project:demo"}, registry=registry, redact=lambda t: t, daily_limit=limit)


@pytest.mark.parametrize("passes", [True, False])
async def test_complete_loop_through_actual_tests_and_next_snapshot(tmp_path, monkeypatch, passes):
    monkeypatch.delenv("ALL_TOMORROW_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr("all_tomorrow.overseer.environment.load_key_pool", lambda: None)
    root, base, registry = project(tmp_path)
    store = InMemoryGoalWorkRunStore()
    sessions = SessionStore(base / "sessions.sqlite")
    reply = lambda prompt, folder: json.dumps({"observations": [], "actions": [fix()], "notes": "시험 결과를 다시 본다"})
    await loop.observe(store, sessions, base, registry=registry, redact=lambda t: t, reasoner=reply, force=True)
    assert len(await store.list_goals()) == 1
    assert await store.claim_pending_work() == []  # 일반 device agent는 검증 전용 일을 가져가지 않는다.

    async def worker(task, candidate):
        assert task["project_id"] == "demo" and candidate != root
        (candidate / "src/demo.py").write_text(f"answer = {2 if passes else 3}\n", encoding="utf-8")
        return {"worker": "fake-cli", "usage": {"input_tokens": 10, "output_tokens": 5}}

    assert await loop.execute_pending(store, base, registry=registry, redact=lambda t: t,
                                      worker=worker, reviewer=lambda *a: True) == 1
    created = next(e for e in await store.list_events() if e.type == "researcher.create_work")
    work = await store.get_work(created.work_id)
    assert work.status == (WorkStatus.SUCCEEDED if passes else WorkStatus.FAILED)
    assert (root / "src/demo.py").read_text(encoding="utf-8") == f"answer = {2 if passes else 1}\n"
    assert (base / "changes" / str(work.work_id) / "before/src/demo.py").read_text() == "answer = 1\n"
    assert all(not r.is_active() for r in await store.list_runs(work.work_id))
    assert list((base / "reports").glob("*.json"))
    snapshots = []

    def next_reasoner(prompt, folder):
        path = Path(prompt.split("스냅샷 파일: ")[1].splitlines()[0])
        snapshots.append(json.loads(path.read_text(encoding="utf-8")))
        return '{"actions": [], "observations": [], "notes": ""}'

    await loop.observe(store, sessions, base, registry=registry, redact=lambda t: t, reasoner=next_reasoner)
    types = {e["type"] for e in snapshots[0]["central"]["events"]}
    assert ("metacog.applied" if passes else "metacog.rolled_back") in types
    # 새 materializer와 새 wake에서도 같은 문제를 중복 생성하지 않는다.
    await make_work(store, registry, wid="another-wake")
    assert len(await store.list_goals()) == 1
    sessions.close()


async def test_dedup_budget_and_atomic_rollback(tmp_path):
    _, _, registry = project(tmp_path)
    store = InMemoryGoalWorkRunStore()
    await asyncio.gather(make_work(store, registry, wid="a"), make_work(store, registry, wid="b"))
    assert len(await store.list_goals()) == 1
    result = await make_work(store, registry, fix(problem_key="different"), wid="c", limit=1)
    assert result == [{"budget_deferred": True}]
    assert len(await store.list_goals()) == 1
    with pytest.raises(ValueError):
        async with store.autonomous_batch() as tx:
            await tx.append_event(loop.event("should.rollback"))
            raise ValueError("transaction failed")
    assert not any(e.type == "should.rollback" for e in await store.list_events())


@pytest.mark.parametrize("action", [fix(authority="permission_or_cost"), fix(authority="direction"),
    fix(project_id="outside"), fix(kind="ask"), fix(authority="user_data_deletion")])
async def test_approval_boundaries_only_produce_questions(tmp_path, action):
    _, base, registry = project(tmp_path)
    store = InMemoryGoalWorkRunStore()
    await make_work(store, registry, action)
    assert not await store.list_goals()
    await reports.sync_events(store, base)
    assert "질문" in next((base / "reports").glob("*.json")).read_text(encoding="utf-8")


async def test_deleted_candidate_file_is_held_and_original_survives(tmp_path):
    root, base, registry = project(tmp_path)
    store = InMemoryGoalWorkRunStore()
    await make_work(store, registry)

    async def worker(task, candidate):
        (candidate / "src/demo.py").unlink()
        return {}

    await loop.execute_pending(store, base, registry=registry, redact=lambda t: t,
                               worker=worker, reviewer=lambda *a: True)
    assert (root / "src/demo.py").exists()
    assert (await loop.central_snapshot(store))["work"][0]["status"] == "WAITING"


async def test_restart_rolls_back_partial_promotion_without_reexecuting(tmp_path):
    root, base, registry = project(tmp_path)
    store = InMemoryGoalWorkRunStore()
    await make_work(store, registry)
    created = next(e for e in await store.list_events() if e.type == "researcher.create_work")
    work = await store.get_work(created.work_id)
    work = await store.transition_work_status(work.work_id, WorkStatus.RUNNING, work.revision, loop.event("started"))
    change = ProjectChange(root, base / "changes" / str(work.work_id))
    change.prepare()
    (change.candidate / "src/demo.py").write_text("answer = 2\n")
    change.apply(change.plan(digest(tree(change.candidate)), digest(tree(change.before))))
    assert (root / "src/demo.py").read_text() == "answer = 2\n"
    await loop.execute_pending(store, base, registry=registry, redact=lambda t: t,
                               worker=lambda *a: pytest.fail("재실행 금지"))
    assert (root / "src/demo.py").read_text() == "answer = 1\n"
    assert (await store.get_work(work.work_id)).status == WorkStatus.FAILED


def test_promotion_verify_failure_restores_dirty_original(tmp_path):
    from all_tomorrow.improve.promotion import Promoter, ProtectionClass, MonitoringPolicy
    root, base, _ = project(tmp_path)
    change = ProjectChange(root, base / "change")
    change.prepare()
    (change.candidate / "src/demo.py").write_text("answer = 2\n")
    change.verify = lambda ref: False
    result = Promoter(change).promote(candidate_ref=digest(tree(change.candidate)),
        accepted_baseline_ref=digest(tree(change.before)), protection_class=ProtectionClass.ORDINARY,
        monitoring_policy=MonitoringPolicy(1, ("mismatch",)))
    assert result.rolled_back and not result.promoted
    assert (root / "src/demo.py").read_text() == "answer = 1\n"


def test_interrupted_temporary_write_is_archived_on_rollback(tmp_path):
    from all_tomorrow.overseer.workspace import save
    root, base, _ = project(tmp_path)
    change = ProjectChange(root, base / "change")
    change.prepare()
    data = json.loads(change.manifest.read_text())
    data.update(state="applying", changed=["src/demo.py"], candidate=tree(change.candidate),
                temporary="src/demo.py.all-tomorrow-change.tmp")
    (root / data["temporary"]).write_text("partial write")
    save(change.manifest, data)
    assert change.rollback(digest(data["baseline"])) == digest(data["baseline"])
    assert (change.artifact / "interrupted-write.tmp").read_text() == "partial write"


def test_reports_flush_backlog_and_retry_without_leaking_webhook(tmp_path, monkeypatch):
    monkeypatch.setenv("ALL_TOMORROW_DISCORD_TRANSPORT", "webhook")
    monkeypatch.setattr("all_tomorrow.overseer.environment.load_key_pool", lambda: None)
    monkeypatch.delenv("ALL_TOMORROW_DISCORD_WEBHOOK_URL", raising=False)
    reports.enqueue(tmp_path, "event1", "보고 내용" * 800)
    assert reports.flush(tmp_path) == 0
    monkeypatch.setenv("ALL_TOMORROW_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test/secret")
    calls = []

    def send(url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(204, request=httpx.Request("POST", url))

    assert reports.flush(tmp_path, post=send) == 1
    assert reports.flush(tmp_path, post=send) == 0
    assert len(calls) == 3 and all(not c["allowed_mentions"]["parse"] for c in calls)
    assert "secret" not in next((tmp_path / "reports").glob("*.json")).read_text(encoding="utf-8")


def test_idle_quota_reset_and_stale_usage_schedule():
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    def usage(reset, percent=10):
        return {"providers": [{"id": "codex", "status": "connected", "observed_at": now.isoformat(),
            "windows": [{"percent": percent, "resets_at": (now + timedelta(hours=reset)).isoformat()}]}]}
    assert wake_delay(usage(2), 30, now=now)[0] is None
    assert wake_delay(usage(2), None, now=now)[0] is None
    assert wake_delay(usage(2, 100), 900, now=now)[0] is None
    assert wake_delay(usage(-1), 900, now=now)[0] is None
    assert wake_delay(usage(2), 900, now=now)[0] < wake_delay(usage(24), 900, now=now)[0]
    stale = usage(2)
    stale["providers"][0]["observed_at"] = (now - timedelta(hours=2)).isoformat()
    assert wake_delay(stale, 900, now=now)[0] is None


async def test_changed_project_verifier_is_held_instead_of_running_old_authority(tmp_path):
    _, base, registry = project(tmp_path)
    store = InMemoryGoalWorkRunStore()
    await make_work(store, registry)
    registry["demo"]["autonomy"]["verify_argv"] = ["changed-command"]
    await loop.execute_pending(store, base, registry=registry, redact=lambda t: t,
                               worker=lambda *a: pytest.fail("옛 권한으로 실행 금지"))
    assert (await loop.central_snapshot(store))["work"][0]["status"] == "WAITING"


async def test_metacog_selects_frozen_tests_without_asking_user(tmp_path, monkeypatch):
    monkeypatch.setenv("ALL_TOMORROW_ADMIN_USER", "actual-admin")
    _, _, registry = project(tmp_path)
    registry["demo"].pop("autonomy")
    store = InMemoryGoalWorkRunStore()
    await make_work(store, registry, fix(verify_argv=["{python}", "-m", "pytest", "-q"]))
    created = next(e for e in await store.list_events() if e.type == "researcher.create_work")
    assert created.payload["decision"]["verify_source"] == "metacog"
    assert (await store.get_goal(created.goal_id)).user_id == "actual-admin"
    assert (await loop.central_snapshot(store))["work"]
    assert not any(e.type == "metacog.question" for e in await store.list_events())
