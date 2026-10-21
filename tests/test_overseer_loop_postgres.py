"""전용 시험 DB가 제공된 경우에만 실제 재시작·트랜잭션을 검증한다."""
import asyncio
import os
from uuid import uuid4

import pytest

from all_tomorrow.overseer.loop import materialize_actions, event
from all_tomorrow.storage.postgres import PostgresStore
from all_tomorrow.storage.semantic_store import PostgresGoalWorkRunStore


async def test_postgres_dedup_survives_restart_and_transaction_rolls_back(tmp_path):
    url = os.environ.get("AT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("AT_TEST_POSTGRES_URL이 있는 전용 시험 DB에서만 실행")
    from all_tomorrow.overseer.environment import REPO
    tag = uuid4().hex
    registry = {"test": {"path": str(tmp_path), "autonomy": {"verify_argv": ["{python}", "-m", "pytest", "-q"]}}}
    action = {"kind": "fix", "title": "영속성 검증", "detail": "시험 전용 일", "authority": "ordinary",
              "project_id": "test", "problem_key": tag, "evidence_refs": ["project:test"]}
    store = PostgresGoalWorkRunStore(url)
    await store.open()
    try:
        await PostgresStore(url, pool=store.pool).migrate(REPO / "migrations")
        async def create(wake):
            return await materialize_actions(store, [action], wake_id=wake, known_refs={"project:test"},
                                             registry=registry, redact=lambda t: t, daily_limit=10000)
        results = await asyncio.gather(create(tag + "a"), create(tag + "b"))
        assert sum("work_id" in r[0] for r in results) == 1
        with pytest.raises(ValueError):
            async with store.autonomous_batch() as tx:
                await tx.append_event(event("test.rollback", payload={"tag": tag}))
                raise ValueError("rollback")
        assert not any(e.payload.get("tag") == tag for e in await store.list_events())
    finally:
        await store.close()
    fresh = PostgresGoalWorkRunStore(url)
    await fresh.open()
    try:
        result = await materialize_actions(fresh, [action], wake_id=tag + "c", known_refs={"project:test"},
                                          registry=registry, redact=lambda t: t, daily_limit=10000)
        assert result == [{"duplicate": True}]
    finally:
        await fresh.close()
