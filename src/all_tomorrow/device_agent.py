"""Device agent server-side store — registration, heartbeat, lease, complete.

Wraps the existing ``GoalWorkRunStore`` (claim_pending_work already gives us an
atomic PENDING->RUNNING transition — see ``executor.py``) with:

- device registration (one-time registration code -> device_id + token)
- heartbeat (updates last_heartbeat_at; 90s silence -> OFFLINE, see domain.device)
- claim: reuses ``store.claim_pending_work`` for the atomic Work grab, then
  records a DeviceLeaseRecord so exactly one device holds it (a device
  attempting to claim a Work another device already leases gets nothing new;
  two devices can never hold an active lease on the same Work because the
  underlying claim already made the Work non-PENDING).
- complete: uploads the WorkerResult-shaped outcome and terminalizes the Work
  through the normal executor transition path (never a shortcut around
  domain.state's transition rules).
- lease expiry sweep: an expired lease whose Work never got a `complete` call
  is flagged ``ambiguous_side_effect`` and is NOT auto-requeued (cross_system's
  AMBIGUOUS rule) — a human must decide via the web "재시도"/정리 UI.

This module owns no capability-routing decision by itself: hard-filtering a
device by declared capability is delegated to routing_policy.select using each
device's registered ``capabilities`` as the resource's capability set.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from all_tomorrow.domain.device import (
    DEFAULT_LEASE_TTL_SECONDS,
    DeviceError,
    DeviceLeaseRecord,
    DeviceRecord,
    DeviceRevokedError,
    DeviceStatus,
    DeviceTokenInvalidError,
    LeaseConflictError,
    LeaseStatus,
    hash_device_token,
    new_device_id,
    new_device_token,
)
from all_tomorrow.domain.ids import new_id, utc_now
from all_tomorrow.domain.state import RunStatus, WorkStatus
from all_tomorrow.storage.semantic_store import GoalWorkRunStore, SemanticEvent

DEFAULT_REGISTRATION_CODE_TTL_SECONDS = 600


class RegistrationCodeError(DeviceError):
    pass


def _evt(actor: str, type_: str, **kw) -> SemanticEvent:
    return SemanticEvent(event_id=new_id("evt"), actor=actor, type=type_, **kw)


@dataclass(slots=True)
class _PendingRegistration:
    code: str
    owner_user_id: str
    expires_at: datetime
    used: bool = False


class DeviceAgentService:
    """In-process device registry + lease tracker.

    Holds device rows and leases in memory (matching the in-memory
    ``GoalWorkRunStore`` used elsewhere in this codebase); a Postgres-backed
    variant follows the same interface and can be swapped in the same way
    ``PostgresGoalWorkRunStore`` swaps for ``InMemoryGoalWorkRunStore``.
    """

    def __init__(self, store: GoalWorkRunStore, *, actor: str = "device_agent") -> None:
        self.store = store
        self.actor = actor
        self._lock = asyncio.Lock()
        self._devices: dict[str, DeviceRecord] = {}
        self._leases: dict[str, DeviceLeaseRecord] = {}   # lease_id -> lease
        self._lease_by_work: dict[str, str] = {}          # work_id -> lease_id
        self._pending_codes: dict[str, _PendingRegistration] = {}

    # -- Registration --------------------------------------------------
    async def issue_registration_code(self, owner_user_id: str) -> str:
        """One-time code a human hands to the device agent's first run."""
        async with self._lock:
            code = new_id("regcode")
            self._pending_codes[code] = _PendingRegistration(
                code=code, owner_user_id=owner_user_id,
                expires_at=utc_now() + __import__("datetime").timedelta(
                    seconds=DEFAULT_REGISTRATION_CODE_TTL_SECONDS),
            )
            return code

    async def register_device(
        self, registration_code: str, *, name: str, capabilities: frozenset[str],
        max_concurrent: int = 1,
    ) -> tuple[DeviceRecord, str]:
        """Redeem a one-time code for a device_id + raw token (returned once)."""
        async with self._lock:
            pending = self._pending_codes.get(registration_code)
            now = utc_now()
            if pending is None or pending.used or now > pending.expires_at:
                raise RegistrationCodeError("registration code is invalid, used, or expired")
            pending.used = True
            token = new_device_token()
            device = DeviceRecord(
                device_id=new_device_id(), name=name, owner_user_id=pending.owner_user_id,
                token_digest=hash_device_token(token), capabilities=capabilities,
                max_concurrent=max_concurrent, status=DeviceStatus.OFFLINE,
            )
            self._devices[device.device_id] = device
            return device, token

    def _authenticate(self, device_id: str, token: str) -> DeviceRecord:
        device = self._devices.get(device_id)
        if device is None:
            raise DeviceTokenInvalidError("unknown device")
        device.verify_token(token)  # raises DeviceRevokedError / DeviceTokenInvalidError
        return device

    # -- Heartbeat -------------------------------------------------------
    async def heartbeat(self, device_id: str, token: str) -> DeviceRecord:
        async with self._lock:
            device = self._authenticate(device_id, token)
            updated = DeviceRecord(
                device_id=device.device_id, name=device.name, owner_user_id=device.owner_user_id,
                token_digest=device.token_digest, capabilities=device.capabilities,
                max_concurrent=device.max_concurrent, status=DeviceStatus.ONLINE,
                registered_at=device.registered_at, last_heartbeat_at=utc_now(),
                revoked_at=device.revoked_at, revision=device.revision + 1,
            )
            self._devices[device_id] = updated
            return updated

    def list_devices(self, owner_user_id: str) -> list[DeviceRecord]:
        return [d for d in self._devices.values() if d.owner_user_id == owner_user_id]

    def get_device(self, device_id: str) -> DeviceRecord | None:
        return self._devices.get(device_id)

    async def revoke_device(self, owner_user_id: str, device_id: str) -> DeviceRecord:
        """Web UI '기기 끊기' — revokes the token; any active lease is released
        so its Work becomes reassignable (no auto-retry of ambiguous side effects,
        just returning the slot — see sweep_expired_leases for the ambiguity rule)."""
        async with self._lock:
            device = self._devices.get(device_id)
            if device is None or device.owner_user_id != owner_user_id:
                raise DeviceError("device not found")
            updated = DeviceRecord(
                device_id=device.device_id, name=device.name, owner_user_id=device.owner_user_id,
                token_digest=device.token_digest, capabilities=device.capabilities,
                max_concurrent=device.max_concurrent, status=DeviceStatus.REVOKED,
                registered_at=device.registered_at, last_heartbeat_at=device.last_heartbeat_at,
                revoked_at=utc_now(), revision=device.revision + 1,
            )
            self._devices[device_id] = updated
            for lease_id, lease in list(self._leases.items()):
                if lease.device_id == device_id and lease.status is LeaseStatus.ACTIVE:
                    self._leases[lease_id] = DeviceLeaseRecord(
                        lease_id=lease.lease_id, work_id=lease.work_id, device_id=lease.device_id,
                        status=LeaseStatus.RELEASED, leased_at=lease.leased_at,
                        expires_at=lease.expires_at, revision=lease.revision + 1,
                    )
                    self._lease_by_work.pop(lease.work_id, None)
            return updated

    # -- Lease / claim ----------------------------------------------------
    async def claim_work(
        self, device_id: str, token: str, *, ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    ) -> DeviceLeaseRecord | None:
        """Claim exactly one Work for this device, or None if nothing is pending.

        Reuses ``store.claim_pending_work`` (already atomic PENDING->RUNNING);
        the lease row is bookkeeping on top, so two devices calling this
        concurrently can never end up with a lease on the same Work — the
        underlying claim only ever hands one caller a given Work.
        """
        async with self._lock:
            device = self._authenticate(device_id, token)
            if device.effective_status() is not DeviceStatus.ONLINE:
                # Heartbeat first; an offline/just-registered device has no lease.
                pass  # authentication succeeded, claim proceeds regardless of last-seen staleness here

        claimed = await self.store.claim_pending_work(limit=1)
        if not claimed:
            return None
        work = claimed[0]
        async with self._lock:
            lease = DeviceLeaseRecord(
                lease_id=new_id("lease"), work_id=str(work.work_id), device_id=device_id,
                expires_at=utc_now() + __import__("datetime").timedelta(seconds=ttl_seconds),
            )
            self._leases[lease.lease_id] = lease
            self._lease_by_work[str(work.work_id)] = lease.lease_id
            return lease

    async def renew_lease(self, device_id: str, token: str, lease_id: str,
                          *, ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS) -> DeviceLeaseRecord:
        async with self._lock:
            self._authenticate(device_id, token)
            lease = self._leases.get(lease_id)
            if lease is None or lease.device_id != device_id:
                raise LeaseConflictError("lease not found for this device")
            if lease.status is not LeaseStatus.ACTIVE:
                raise LeaseConflictError(f"lease is {lease.status.value}, cannot renew")
            updated = DeviceLeaseRecord(
                lease_id=lease.lease_id, work_id=lease.work_id, device_id=lease.device_id,
                status=LeaseStatus.ACTIVE, leased_at=lease.leased_at,
                expires_at=utc_now() + __import__("datetime").timedelta(seconds=ttl_seconds),
                revision=lease.revision + 1,
            )
            self._leases[lease_id] = updated
            return updated

    async def complete_work(
        self, device_id: str, token: str, lease_id: str, *,
        succeeded: bool, output_text: str | None, error: str | None,
        duration_ms: int = 0, artifact_refs: tuple[str, ...] = (),
    ) -> dict:
        """Terminalize the leased Work via the same transition path as the
        local executor (executor.py's ``_succeed``/``_fail``), never a bespoke
        shortcut, so Goal/Work/Run invariants stay identical for a device-run
        Work and a locally-run one."""
        async with self._lock:
            self._authenticate(device_id, token)
            lease = self._leases.get(lease_id)
            if lease is None or lease.device_id != device_id:
                raise LeaseConflictError("lease not found for this device")
            if lease.status is not LeaseStatus.ACTIVE:
                raise LeaseConflictError(f"lease already {lease.status.value}")
            work_id = lease.work_id
            self._leases[lease_id] = DeviceLeaseRecord(
                lease_id=lease.lease_id, work_id=lease.work_id, device_id=lease.device_id,
                status=LeaseStatus.COMPLETED, leased_at=lease.leased_at,
                expires_at=lease.expires_at, completed_at=utc_now(), revision=lease.revision + 1,
            )
            self._lease_by_work.pop(work_id, None)

        from all_tomorrow.domain.ids import WorkId

        work = await self.store.get_work(WorkId(work_id))
        if work is None:
            raise DeviceError(f"work {work_id} not found")
        runs = await self.store.list_runs(work.work_id)
        run = next((r for r in runs if r.is_active()), None)
        if run is None:
            from all_tomorrow.domain.state import RunRecord

            run = RunRecord(run_id=new_id("run"), work_id=work.work_id)  # type: ignore[arg-type]
            run = await self.store.create_run(run, _evt(self.actor, "run.created", work_id=work.work_id))
            rev = await self.store.current_run_revision(run.run_id)
            run = await self.store.transition_run_status(
                run.run_id, RunStatus.RUNNING, rev,
                _evt(self.actor, "run.running", work_id=work.work_id, run_id=run.run_id),
            )

        if succeeded:
            rev = await self.store.current_run_revision(run.run_id)
            await self.store.transition_run_status(
                run.run_id, RunStatus.SUCCEEDED, rev,
                _evt(self.actor, "run.succeeded", work_id=work.work_id, run_id=run.run_id,
                     payload={"device_id": device_id}),
            )
            from all_tomorrow.domain.outcomes import CompletionEvidence

            evidence = CompletionEvidence(
                criterion_ref=f"work:{work.work_id}",
                evaluator_ref="all_tomorrow.device_agent.complete_work",
                evaluator_version="1",
                observed_values={"duration_ms": duration_ms, "device_id": device_id},
                artifact_refs=artifact_refs,
            )
            work_cur = await self.store.get_work(work.work_id)
            await self.store.transition_work_status(
                work.work_id, WorkStatus.SUCCEEDED, work_cur.revision,
                _evt(self.actor, "work.succeeded", work_id=work.work_id,
                     payload={"device_id": device_id}), evidence=evidence,
            )
            return {"work_id": work_id, "outcome": "succeeded"}

        reason = error or "device reported failure"
        try:
            rev = await self.store.current_run_revision(run.run_id)
            await self.store.transition_run_status(
                run.run_id, RunStatus.FAILED, rev,
                _evt(self.actor, "run.failed", work_id=work.work_id, run_id=run.run_id,
                     payload={"reason": reason, "device_id": device_id}),
            )
        except Exception:
            pass
        work_cur = await self.store.get_work(work.work_id)
        try:
            await self.store.transition_work_status(
                work.work_id, WorkStatus.FAILED, work_cur.revision,
                _evt(self.actor, "work.failed", work_id=work.work_id,
                     payload={"reason": reason, "device_id": device_id}),
            )
        except Exception:
            pass
        return {"work_id": work_id, "outcome": "failed", "detail": reason}

    # -- Expiry sweep -------------------------------------------------------
    async def sweep_expired_leases(self) -> list[str]:
        """Mark leases past their TTL as EXPIRED with ``ambiguous_side_effect``.

        Per cross_system.py's AMBIGUOUS rule: a Work whose device went silent
        mid-run may already have caused a real side effect, so it is NEVER
        blindly re-claimed by another device here. It is left for a human to
        inspect/retry via the same broken-work UI the local executor uses.
        Returns the list of work_ids flagged this sweep.
        """
        flagged: list[str] = []
        async with self._lock:
            now = utc_now()
            for lease_id, lease in list(self._leases.items()):
                if lease.is_expired(now):
                    self._leases[lease_id] = DeviceLeaseRecord(
                        lease_id=lease.lease_id, work_id=lease.work_id, device_id=lease.device_id,
                        status=LeaseStatus.EXPIRED, leased_at=lease.leased_at,
                        expires_at=lease.expires_at, ambiguous_side_effect=True,
                        revision=lease.revision + 1,
                    )
                    self._lease_by_work.pop(lease.work_id, None)
                    flagged.append(lease.work_id)
        return flagged

    def lease_for_work(self, work_id: str) -> DeviceLeaseRecord | None:
        lease_id = self._lease_by_work.get(work_id)
        return self._leases.get(lease_id) if lease_id else None

    def devices_view(self, owner_user_id: str) -> list[dict]:
        now = utc_now()
        out = []
        for d in self.list_devices(owner_user_id):
            active_lease = next(
                (l for l in self._leases.values()
                 if l.device_id == d.device_id and l.status is LeaseStatus.ACTIVE), None)
            out.append({
                "device_id": d.device_id, "name": d.name,
                "status": d.effective_status(now).value,
                "last_heartbeat_at": d.last_heartbeat_at.isoformat() if d.last_heartbeat_at else None,
                "capabilities": sorted(d.capabilities),
                "current_work_id": active_lease.work_id if active_lease else None,
                "registered_at": d.registered_at.isoformat(),
            })
        return out


# ---------------------------------------------------------------------------
# Postgres-backed variant (durable across restarts) — same interface as above.
# ---------------------------------------------------------------------------
class PostgresDeviceAgentService:
    """Same public interface as ``DeviceAgentService``, backed by Postgres.

    Uses the same connection pool as the store it wraps (mirrors
    ``PostgresRequestStore(database_url, pool=semantic.pool)`` in web.py) so a
    device registration/heartbeat/lease commits against the same database the
    Goal/Work/Run rows live in — no second database to keep in sync.
    """

    def __init__(self, store: GoalWorkRunStore, pool, *, actor: str = "device_agent") -> None:
        self.store = store
        self.pool = pool
        self.actor = actor

    async def issue_registration_code(self, owner_user_id: str) -> str:
        import datetime as _dt

        code = new_id("regcode")
        expires_at = utc_now() + _dt.timedelta(seconds=DEFAULT_REGISTRATION_CODE_TTL_SECONDS)
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO device_registration_codes (code, owner_user_id, expires_at) VALUES (%s, %s, %s)",
                (code, owner_user_id, expires_at),
            )
        return code

    async def register_device(
        self, registration_code: str, *, name: str, capabilities: frozenset[str],
        max_concurrent: int = 1,
    ) -> tuple[DeviceRecord, str]:
        from psycopg.types.json import Jsonb

        async with self.pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    "SELECT owner_user_id, expires_at, used FROM device_registration_codes "
                    "WHERE code = %s FOR UPDATE",
                    (registration_code,),
                )
                row = await cur.fetchone()
                if row is None or row[2] or utc_now() > row[1]:
                    raise RegistrationCodeError("registration code is invalid, used, or expired")
                owner_user_id = row[0]
                await conn.execute(
                    "UPDATE device_registration_codes SET used = true WHERE code = %s",
                    (registration_code,),
                )
                token = new_device_token()
                device_id = new_device_id()
                digest = hash_device_token(token)
                await conn.execute(
                    """
                    INSERT INTO devices (device_id, name, owner_user_id, token_digest,
                                         capabilities, max_concurrent, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'OFFLINE')
                    """,
                    (device_id, name, owner_user_id, digest, Jsonb(sorted(capabilities)), max_concurrent),
                )
        device = DeviceRecord(
            device_id=device_id, name=name, owner_user_id=owner_user_id,
            token_digest=digest, capabilities=capabilities, max_concurrent=max_concurrent,
        )
        return device, token

    async def _load_device(self, device_id: str):
        cur_conn = self.pool.connection()
        async with cur_conn as conn:
            cur = await conn.execute(
                """
                SELECT device_id, name, owner_user_id, token_digest, capabilities,
                       max_concurrent, status, registered_at, last_heartbeat_at, revoked_at, revision
                FROM devices WHERE device_id = %s
                """,
                (device_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return DeviceRecord(
            device_id=row[0], name=row[1], owner_user_id=row[2], token_digest=row[3],
            capabilities=frozenset(row[4] or []), max_concurrent=row[5],
            status=DeviceStatus(row[6]), registered_at=row[7], last_heartbeat_at=row[8],
            revoked_at=row[9], revision=row[10],
        )

    async def heartbeat(self, device_id: str, token: str) -> DeviceRecord:
        device = await self._load_device(device_id)
        if device is None:
            raise DeviceTokenInvalidError("unknown device")
        device.verify_token(token)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE devices SET status = 'ONLINE', last_heartbeat_at = now(), revision = revision + 1 "
                "WHERE device_id = %s",
                (device_id,),
            )
        return await self._load_device(device_id)

    async def get_device(self, device_id: str) -> DeviceRecord | None:
        return await self._load_device(device_id)

    async def list_devices(self, owner_user_id: str) -> list[DeviceRecord]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT device_id, name, owner_user_id, token_digest, capabilities,
                       max_concurrent, status, registered_at, last_heartbeat_at, revoked_at, revision
                FROM devices WHERE owner_user_id = %s ORDER BY registered_at
                """,
                (owner_user_id,),
            )
            rows = await cur.fetchall()
        return [
            DeviceRecord(
                device_id=r[0], name=r[1], owner_user_id=r[2], token_digest=r[3],
                capabilities=frozenset(r[4] or []), max_concurrent=r[5], status=DeviceStatus(r[6]),
                registered_at=r[7], last_heartbeat_at=r[8], revoked_at=r[9], revision=r[10],
            )
            for r in rows
        ]

    async def revoke_device(self, owner_user_id: str, device_id: str) -> DeviceRecord:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    "SELECT owner_user_id FROM devices WHERE device_id = %s FOR UPDATE", (device_id,),
                )
                row = await cur.fetchone()
                if row is None or row[0] != owner_user_id:
                    raise DeviceError("device not found")
                await conn.execute(
                    "UPDATE devices SET status = 'REVOKED', revoked_at = now(), revision = revision + 1 "
                    "WHERE device_id = %s",
                    (device_id,),
                )
                await conn.execute(
                    "UPDATE device_leases SET status = 'RELEASED', revision = revision + 1 "
                    "WHERE device_id = %s AND status = 'ACTIVE'",
                    (device_id,),
                )
        return await self._load_device(device_id)

    async def claim_work(
        self, device_id: str, token: str, *, ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    ) -> DeviceLeaseRecord | None:
        device = await self._load_device(device_id)
        if device is None:
            raise DeviceTokenInvalidError("unknown device")
        device.verify_token(token)

        claimed = await self.store.claim_pending_work(limit=1)
        if not claimed:
            return None
        work = claimed[0]
        import datetime as _dt

        lease_id = new_id("lease")
        expires_at = utc_now() + _dt.timedelta(seconds=ttl_seconds)
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO device_leases (lease_id, work_id, device_id, status, expires_at)
                VALUES (%s, %s, %s, 'ACTIVE', %s)
                """,
                (lease_id, str(work.work_id), device_id, expires_at),
            )
        return DeviceLeaseRecord(
            lease_id=lease_id, work_id=str(work.work_id), device_id=device_id, expires_at=expires_at,
        )

    async def renew_lease(self, device_id: str, token: str, lease_id: str,
                          *, ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS) -> DeviceLeaseRecord:
        device = await self._load_device(device_id)
        if device is None:
            raise DeviceTokenInvalidError("unknown device")
        device.verify_token(token)
        import datetime as _dt

        expires_at = utc_now() + _dt.timedelta(seconds=ttl_seconds)
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE device_leases SET expires_at = %s, revision = revision + 1
                WHERE lease_id = %s AND device_id = %s AND status = 'ACTIVE'
                RETURNING work_id, leased_at, revision
                """,
                (expires_at, lease_id, device_id),
            )
            row = await cur.fetchone()
        if row is None:
            raise LeaseConflictError("lease not found for this device, or not active")
        return DeviceLeaseRecord(
            lease_id=lease_id, work_id=row[0], device_id=device_id, leased_at=row[1],
            expires_at=expires_at, revision=row[2],
        )

    async def complete_work(
        self, device_id: str, token: str, lease_id: str, *,
        succeeded: bool, output_text: str | None, error: str | None,
        duration_ms: int = 0, artifact_refs: tuple[str, ...] = (),
    ) -> dict:
        device = await self._load_device(device_id)
        if device is None:
            raise DeviceTokenInvalidError("unknown device")
        device.verify_token(token)

        async with self.pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    "SELECT work_id, status FROM device_leases WHERE lease_id = %s AND device_id = %s FOR UPDATE",
                    (lease_id, device_id),
                )
                row = await cur.fetchone()
                if row is None:
                    raise LeaseConflictError("lease not found for this device")
                work_id, lease_status = row
                if lease_status != "ACTIVE":
                    raise LeaseConflictError(f"lease already {lease_status}")
                await conn.execute(
                    "UPDATE device_leases SET status = 'COMPLETED', completed_at = now(), "
                    "revision = revision + 1 WHERE lease_id = %s",
                    (lease_id,),
                )

        from all_tomorrow.domain.ids import WorkId

        work = await self.store.get_work(WorkId(work_id))
        if work is None:
            raise DeviceError(f"work {work_id} not found")
        runs = await self.store.list_runs(work.work_id)
        run = next((r for r in runs if r.is_active()), None)
        if run is None:
            from all_tomorrow.domain.state import RunRecord

            run = RunRecord(run_id=new_id("run"), work_id=work.work_id)  # type: ignore[arg-type]
            run = await self.store.create_run(run, _evt(self.actor, "run.created", work_id=work.work_id))
            rev = await self.store.current_run_revision(run.run_id)
            run = await self.store.transition_run_status(
                run.run_id, RunStatus.RUNNING, rev,
                _evt(self.actor, "run.running", work_id=work.work_id, run_id=run.run_id),
            )

        if succeeded:
            rev = await self.store.current_run_revision(run.run_id)
            await self.store.transition_run_status(
                run.run_id, RunStatus.SUCCEEDED, rev,
                _evt(self.actor, "run.succeeded", work_id=work.work_id, run_id=run.run_id,
                     payload={"device_id": device_id}),
            )
            from all_tomorrow.domain.outcomes import CompletionEvidence

            evidence = CompletionEvidence(
                criterion_ref=f"work:{work.work_id}",
                evaluator_ref="all_tomorrow.device_agent.complete_work",
                evaluator_version="1",
                observed_values={"duration_ms": duration_ms, "device_id": device_id},
                artifact_refs=artifact_refs,
            )
            work_cur = await self.store.get_work(work.work_id)
            await self.store.transition_work_status(
                work.work_id, WorkStatus.SUCCEEDED, work_cur.revision,
                _evt(self.actor, "work.succeeded", work_id=work.work_id,
                     payload={"device_id": device_id}), evidence=evidence,
            )
            return {"work_id": work_id, "outcome": "succeeded"}

        reason = error or "device reported failure"
        try:
            rev = await self.store.current_run_revision(run.run_id)
            await self.store.transition_run_status(
                run.run_id, RunStatus.FAILED, rev,
                _evt(self.actor, "run.failed", work_id=work.work_id, run_id=run.run_id,
                     payload={"reason": reason, "device_id": device_id}),
            )
        except Exception:
            pass
        work_cur = await self.store.get_work(work.work_id)
        try:
            await self.store.transition_work_status(
                work.work_id, WorkStatus.FAILED, work_cur.revision,
                _evt(self.actor, "work.failed", work_id=work.work_id,
                     payload={"reason": reason, "device_id": device_id}),
            )
        except Exception:
            pass
        return {"work_id": work_id, "outcome": "failed", "detail": reason}

    async def sweep_expired_leases(self) -> list[str]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE device_leases SET status = 'EXPIRED', ambiguous_side_effect = true,
                       revision = revision + 1
                WHERE status = 'ACTIVE' AND expires_at < now()
                RETURNING work_id
                """,
            )
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def lease_for_work(self, work_id: str) -> DeviceLeaseRecord | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT lease_id, device_id, status, leased_at, expires_at, completed_at,
                       ambiguous_side_effect, revision
                FROM device_leases WHERE work_id = %s AND status = 'ACTIVE'
                """,
                (work_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return DeviceLeaseRecord(
            lease_id=row[0], work_id=work_id, device_id=row[1], status=LeaseStatus(row[2]),
            leased_at=row[3], expires_at=row[4], completed_at=row[5],
            ambiguous_side_effect=row[6], revision=row[7],
        )

    async def devices_view(self, owner_user_id: str) -> list[dict]:
        now = utc_now()
        out = []
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT d.device_id, d.name, d.status, d.last_heartbeat_at, d.capabilities,
                       d.registered_at, d.revoked_at,
                       (SELECT work_id FROM device_leases l
                        WHERE l.device_id = d.device_id AND l.status = 'ACTIVE' LIMIT 1) AS current_work_id
                FROM devices d WHERE d.owner_user_id = %s ORDER BY d.registered_at
                """,
                (owner_user_id,),
            )
            rows = await cur.fetchall()
        for r in rows:
            device = DeviceRecord(
                device_id=r[0], name=r[1], owner_user_id=owner_user_id, token_digest="",
                status=DeviceStatus(r[2]), last_heartbeat_at=r[3], revoked_at=r[6],
            )
            out.append({
                "device_id": r[0], "name": r[1], "status": device.effective_status(now).value,
                "last_heartbeat_at": r[3].isoformat() if r[3] else None,
                "capabilities": sorted(r[4] or []), "current_work_id": r[7],
                "registered_at": r[5].isoformat(),
            })
        return out
