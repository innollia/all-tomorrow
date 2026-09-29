"""Device agent: registration, heartbeat, lease/claim, complete, revoke."""

from __future__ import annotations

import asyncio

import pytest

from all_tomorrow.device_agent import (
    DeviceAgentService,
    DeviceRevokedError,
    DeviceTokenInvalidError,
    LeaseConflictError,
    RegistrationCodeError,
)
from all_tomorrow.domain.device import DeviceStatus, OFFLINE_AFTER_SECONDS
from all_tomorrow.domain.ids import new_event_id, new_goal_id, new_work_id
from all_tomorrow.domain.state import GoalRecord, WorkRecord, WorkStatus
from all_tomorrow.storage.semantic_store import InMemoryGoalWorkRunStore, SemanticEvent


async def _make_work(store: InMemoryGoalWorkRunStore, *, title: str = "test work") -> WorkRecord:
    goal = GoalRecord(goal_id=new_goal_id(), user_id="innollia", title=title)
    await store.create_goal(
        goal, SemanticEvent(event_id=new_event_id(), actor="test", type="goal.created", goal_id=goal.goal_id)
    )
    work = WorkRecord(work_id=new_work_id(), goal_id=goal.goal_id, title=title)
    await store.create_work(
        work, SemanticEvent(event_id=new_event_id(), actor="test", type="work.created",
                            goal_id=goal.goal_id, work_id=work.work_id),
    )
    return work


@pytest.fixture
def store() -> InMemoryGoalWorkRunStore:
    return InMemoryGoalWorkRunStore()


@pytest.fixture
def service(store: InMemoryGoalWorkRunStore) -> DeviceAgentService:
    return DeviceAgentService(store)


async def test_register_and_heartbeat_marks_online(service: DeviceAgentService) -> None:
    code = await service.issue_registration_code("innollia")
    device, token = await service.register_device(code, name="dp7", capabilities=frozenset({"kiro"}))
    assert device.status is DeviceStatus.OFFLINE  # never seen a heartbeat yet

    updated = await service.heartbeat(device.device_id, token)
    assert updated.status is DeviceStatus.ONLINE


async def test_registration_code_is_single_use(service: DeviceAgentService) -> None:
    code = await service.issue_registration_code("innollia")
    await service.register_device(code, name="dp7", capabilities=frozenset())
    with pytest.raises(RegistrationCodeError):
        await service.register_device(code, name="dp7-again", capabilities=frozenset())


async def test_wrong_token_is_rejected(service: DeviceAgentService) -> None:
    code = await service.issue_registration_code("innollia")
    device, _token = await service.register_device(code, name="dp7", capabilities=frozenset())
    with pytest.raises(DeviceTokenInvalidError):
        await service.heartbeat(device.device_id, "not-the-real-token")


async def test_two_devices_never_claim_the_same_work(
    service: DeviceAgentService, store: InMemoryGoalWorkRunStore,
) -> None:
    await _make_work(store)
    code1 = await service.issue_registration_code("innollia")
    d1, t1 = await service.register_device(code1, name="dp7", capabilities=frozenset())
    await service.heartbeat(d1.device_id, t1)
    code2 = await service.issue_registration_code("innollia")
    d2, t2 = await service.register_device(code2, name="aaaa", capabilities=frozenset())
    await service.heartbeat(d2.device_id, t2)

    lease1, lease2 = await asyncio.gather(
        service.claim_work(d1.device_id, t1), service.claim_work(d2.device_id, t2)
    )
    leases = [l for l in (lease1, lease2) if l is not None]
    assert len(leases) == 1  # only one Work existed; exactly one device got it


async def test_complete_success_terminalizes_work(
    service: DeviceAgentService, store: InMemoryGoalWorkRunStore,
) -> None:
    work = await _make_work(store)
    code = await service.issue_registration_code("innollia")
    device, token = await service.register_device(code, name="dp7", capabilities=frozenset())
    await service.heartbeat(device.device_id, token)
    lease = await service.claim_work(device.device_id, token)
    assert lease is not None
    assert lease.work_id == str(work.work_id)

    result = await service.complete_work(
        device.device_id, token, lease.lease_id, succeeded=True,
        output_text="done", error=None, duration_ms=42,
    )
    assert result["outcome"] == "succeeded"
    updated = await store.get_work(work.work_id)
    assert updated.status is WorkStatus.SUCCEEDED


async def test_complete_failure_fails_work(
    service: DeviceAgentService, store: InMemoryGoalWorkRunStore,
) -> None:
    work = await _make_work(store)
    code = await service.issue_registration_code("innollia")
    device, token = await service.register_device(code, name="dp7", capabilities=frozenset())
    await service.heartbeat(device.device_id, token)
    lease = await service.claim_work(device.device_id, token)
    assert lease is not None

    result = await service.complete_work(
        device.device_id, token, lease.lease_id, succeeded=False,
        output_text=None, error="boom", duration_ms=5,
    )
    assert result["outcome"] == "failed"
    updated = await store.get_work(work.work_id)
    assert updated.status is WorkStatus.FAILED


async def test_double_complete_is_rejected(
    service: DeviceAgentService, store: InMemoryGoalWorkRunStore,
) -> None:
    await _make_work(store)
    code = await service.issue_registration_code("innollia")
    device, token = await service.register_device(code, name="dp7", capabilities=frozenset())
    await service.heartbeat(device.device_id, token)
    lease = await service.claim_work(device.device_id, token)
    assert lease is not None
    await service.complete_work(device.device_id, token, lease.lease_id, succeeded=True,
                                output_text="ok", error=None, duration_ms=1)
    with pytest.raises(LeaseConflictError):
        await service.complete_work(device.device_id, token, lease.lease_id, succeeded=True,
                                    output_text="ok again", error=None, duration_ms=1)


async def test_revoked_device_cannot_heartbeat_or_claim(
    service: DeviceAgentService, store: InMemoryGoalWorkRunStore,
) -> None:
    await _make_work(store)
    code = await service.issue_registration_code("innollia")
    device, token = await service.register_device(code, name="dp7", capabilities=frozenset())
    await service.heartbeat(device.device_id, token)

    revoked = await service.revoke_device("innollia", device.device_id)
    assert revoked.status is DeviceStatus.REVOKED

    with pytest.raises(DeviceRevokedError):
        await service.heartbeat(device.device_id, token)
    with pytest.raises(DeviceRevokedError):
        await service.claim_work(device.device_id, token)


async def test_revoke_releases_active_lease(
    service: DeviceAgentService, store: InMemoryGoalWorkRunStore,
) -> None:
    await _make_work(store)
    code = await service.issue_registration_code("innollia")
    device, token = await service.register_device(code, name="dp7", capabilities=frozenset())
    await service.heartbeat(device.device_id, token)
    lease = await service.claim_work(device.device_id, token)
    assert lease is not None

    await service.revoke_device("innollia", device.device_id)
    assert service.lease_for_work(lease.work_id) is None


async def test_offline_after_90_seconds_of_silence(service: DeviceAgentService) -> None:
    import datetime as dt

    code = await service.issue_registration_code("innollia")
    device, token = await service.register_device(code, name="dp7", capabilities=frozenset())
    updated = await service.heartbeat(device.device_id, token)
    assert updated.effective_status() is DeviceStatus.ONLINE

    from all_tomorrow.domain.device import DeviceRecord

    stale = DeviceRecord(
        device_id=updated.device_id, name=updated.name, owner_user_id=updated.owner_user_id,
        token_digest=updated.token_digest, capabilities=updated.capabilities,
        max_concurrent=updated.max_concurrent, status=updated.status,
        registered_at=updated.registered_at,
        last_heartbeat_at=updated.last_heartbeat_at - dt.timedelta(seconds=OFFLINE_AFTER_SECONDS + 1),
        revoked_at=updated.revoked_at, revision=updated.revision,
    )
    assert stale.effective_status() is DeviceStatus.OFFLINE


async def test_expired_lease_is_flagged_ambiguous_not_reassigned(
    service: DeviceAgentService, store: InMemoryGoalWorkRunStore,
) -> None:
    await _make_work(store)
    code = await service.issue_registration_code("innollia")
    device, token = await service.register_device(code, name="dp7", capabilities=frozenset())
    await service.heartbeat(device.device_id, token)
    lease = await service.claim_work(device.device_id, token, ttl_seconds=0)
    assert lease is not None

    import time

    time.sleep(0.01)
    flagged = await service.sweep_expired_leases()
    assert flagged == [lease.work_id]

    # A second device must NOT be able to pick this Work back up automatically:
    # the underlying Work is already RUNNING (claim_pending_work only claims
    # PENDING Work), so there is nothing left for another device to claim.
    code2 = await service.issue_registration_code("innollia")
    d2, t2 = await service.register_device(code2, name="aaaa", capabilities=frozenset())
    await service.heartbeat(d2.device_id, t2)
    lease2 = await service.claim_work(d2.device_id, t2)
    assert lease2 is None
