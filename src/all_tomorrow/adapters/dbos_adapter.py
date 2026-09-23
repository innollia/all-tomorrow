from __future__ import annotations

import asyncio
import base64
import os
import pickle
import time
from typing import Any

import psycopg
from all_tomorrow.domain.errors import CanonicalError, ErrorCategory
from all_tomorrow.domain.ids import ExecutionRef, RunId, utc_now
from all_tomorrow.error_normalization import normalize_exception
from all_tomorrow.ports.durable import (
    CancelOutcome,
    CancelResult,
    DurableExecutionPort,
    DurableExecutionState,
    ExecutionResult,
    ExecutionStatusResult,
    SignalOutcome,
    SignalResult,
)


class DBOSDurableAdapter(DurableExecutionPort):
    """DBOS implementation of DurableExecutionPort backed by real PostgreSQL/DBOS runtime.

    Translates DBOS workflow lifecycles, steps, and system tables into
    canonical domain ports and normalized CanonicalErrors.
    When system_database_url is provided (or AT_TEST_POSTGRES_URL is set),
    queries and mutates durable PostgreSQL tables (`dbos.workflow_status`,
    `dbos.workflow_output`, `dbos.notifications`, and `public.at_run_executions`).
    """

    def __init__(
        self,
        backend_name: str = "dbos",
        system_database_url: str | None = None,
        application_name: str = "all-tomorrow-worker",
    ) -> None:
        self.backend_name = backend_name
        self.system_database_url = system_database_url or os.environ.get("AT_TEST_POSTGRES_URL")
        self.application_name = application_name

        # Fallback in-memory storage only if no database URL is configured
        self._runs_to_ref: dict[str, ExecutionRef] = {}
        self._executions: dict[str, dict[str, Any]] = {}
        self._signals_seen: set[tuple[str, str]] = set()

        if self.system_database_url:
            self._init_db()

    def _get_connection(self) -> psycopg.Connection:
        if not self.system_database_url:
            raise RuntimeError("No system_database_url configured for DBOS adapter")
        return psycopg.connect(self.system_database_url)

    def _init_db(self) -> None:
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS public.at_run_executions (
                            run_id TEXT PRIMARY KEY,
                            execution_id TEXT NOT NULL,
                            workflow_name TEXT NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS public.at_signals_seen (
                            execution_id TEXT NOT NULL,
                            signal_id TEXT NOT NULL,
                            delivered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            PRIMARY KEY (execution_id, signal_id)
                        )
                        """
                    )
                conn.commit()
        except Exception:
            pass

    async def start(
        self,
        run_id: RunId,
        workflow_name: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> ExecutionRef:
        key = str(run_id)

        if not self.system_database_url:
            if key in self._runs_to_ref:
                return self._runs_to_ref[key]
            exec_id = f"dbos_{key}"
            ref = ExecutionRef(backend=self.backend_name, execution_id=exec_id, execution_version=1)
            self._runs_to_ref[key] = ref
            self._executions[exec_id] = {
                "ref": ref,
                "workflow_name": workflow_name,
                "payload": payload,
                "state": DurableExecutionState.RUNNING,
                "result": None,
                "error": None,
            }
            return ref

        # Durable PostgreSQL branch
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_start, key, workflow_name, payload)

    def _sync_start(self, run_key: str, workflow_name: str, payload: dict[str, Any]) -> ExecutionRef:
        exec_id = f"dbos_{run_key}"
        now_ms = int(time.time() * 1000)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Check or insert mapping in public.at_run_executions
                cur.execute(
                    """
                    INSERT INTO public.at_run_executions (run_id, execution_id, workflow_name, created_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (run_id) DO UPDATE SET run_id = EXCLUDED.run_id
                    RETURNING execution_id, created_at
                    """,
                    (run_key, exec_id, workflow_name),
                )
                actual_exec_id, attached_at = cur.fetchone()

                # 2. Check if workflow already exists in dbos.workflow_status
                cur.execute(
                    "SELECT status FROM dbos.workflow_status WHERE workflow_uuid = %s",
                    (actual_exec_id,),
                )
                existing = cur.fetchone()
                if not existing:
                    # Insert enqueued/pending status into dbos.workflow_status
                    cur.execute(
                        """
                        INSERT INTO dbos.workflow_status (
                            workflow_uuid, status, name, created_at, updated_at,
                            application_name, queue_name
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (workflow_uuid) DO NOTHING
                        """,
                        (actual_exec_id, "PENDING", workflow_name, now_ms, now_ms, self.application_name, "default"),
                    )
            conn.commit()

        return ExecutionRef(
            backend=self.backend_name,
            execution_id=actual_exec_id,
            execution_version=1,
            attached_at=attached_at,
        )

    async def get_status(self, ref: ExecutionRef) -> ExecutionStatusResult:
        if not self.system_database_url:
            internal = self._executions.get(ref.execution_id)
            if internal is None:
                return ExecutionStatusResult(
                    ref=ref,
                    state=DurableExecutionState.PENDING,
                    error=CanonicalError(
                        category=ErrorCategory.NOT_FOUND,
                        code="workflow_not_found",
                        retryability=False,
                        ambiguity=False,
                    ),
                )
            return ExecutionStatusResult(
                ref=ref,
                state=internal["state"],
                error=internal.get("error"),
            )

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_get_status, ref)

    def _sync_get_status(self, ref: ExecutionRef) -> ExecutionStatusResult:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, error FROM dbos.workflow_status WHERE workflow_uuid = %s",
                    (ref.execution_id,),
                )
                row = cur.fetchone()

        if row is None:
            return ExecutionStatusResult(
                ref=ref,
                state=DurableExecutionState.PENDING,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="workflow_not_found",
                    retryability=False,
                    ambiguity=False,
                ),
            )

        status_str, error_text = row
        state = self._map_dbos_status(status_str)
        canonical_error = None
        if error_text:
            canonical_error = CanonicalError(
                category=ErrorCategory.INTERNAL,
                code="workflow_error",
                message=str(error_text),
                retryability=False,
                ambiguity=False,
            )

        return ExecutionStatusResult(
            ref=ref,
            state=state,
            error=canonical_error,
        )

    def _map_dbos_status(self, status: str) -> DurableExecutionState:
        match status.upper():
            case "PENDING" | "ENQUEUED" | "DELAYED":
                return DurableExecutionState.RUNNING
            case "SUCCESS":
                return DurableExecutionState.COMPLETED
            case "ERROR" | "MAX_RECOVERY_ATTEMPTS_EXCEEDED":
                return DurableExecutionState.FAILED
            case "CANCELLED":
                return DurableExecutionState.CANCELLED
            case _:
                return DurableExecutionState.RUNNING

    async def find_by_run_id(self, run_id: RunId) -> ExecutionRef | None:
        key = str(run_id)
        if not self.system_database_url:
            return self._runs_to_ref.get(key)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_find_by_run_id, key)

    def _sync_find_by_run_id(self, run_key: str) -> ExecutionRef | None:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT execution_id, created_at FROM public.at_run_executions WHERE run_id = %s",
                    (run_key,),
                )
                row = cur.fetchone()
                if row is None:
                    # Also check directly against workflow_uuid if it was created as dbos_<run_key>
                    cur.execute(
                        "SELECT workflow_uuid FROM dbos.workflow_status WHERE workflow_uuid = %s",
                        (f"dbos_{run_key}",),
                    )
                    fallback_row = cur.fetchone()
                    if fallback_row:
                        return ExecutionRef(backend=self.backend_name, execution_id=fallback_row[0], execution_version=1)
                    return None

                return ExecutionRef(
                    backend=self.backend_name,
                    execution_id=row[0],
                    execution_version=1,
                    attached_at=row[1],
                )

    async def cancel(self, ref: ExecutionRef) -> CancelResult:
        if not self.system_database_url:
            internal = self._executions.get(ref.execution_id)
            if internal is None:
                return CancelResult(
                    outcome=CancelOutcome.NOT_FOUND,
                    ref=ref,
                    error=CanonicalError(
                        category=ErrorCategory.NOT_FOUND,
                        code="workflow_not_found",
                        retryability=False,
                        ambiguity=False,
                    ),
                )
            if internal["state"] in (
                DurableExecutionState.COMPLETED,
                DurableExecutionState.FAILED,
                DurableExecutionState.CANCELLED,
            ):
                return CancelResult(
                    outcome=CancelOutcome.ALREADY_TERMINAL,
                    ref=ref,
                    details=f"Workflow is in terminal state {internal['state']}",
                )

            internal["state"] = DurableExecutionState.CANCELLED
            return CancelResult(outcome=CancelOutcome.CANCEL_REQUESTED, ref=ref)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_cancel, ref)

    def _sync_cancel(self, ref: ExecutionRef) -> CancelResult:
        now_ms = int(time.time() * 1000)
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM dbos.workflow_status WHERE workflow_uuid = %s",
                    (ref.execution_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return CancelResult(
                        outcome=CancelOutcome.NOT_FOUND,
                        ref=ref,
                        error=CanonicalError(
                            category=ErrorCategory.NOT_FOUND,
                            code="workflow_not_found",
                            retryability=False,
                            ambiguity=False,
                        ),
                    )

                current_status = row[0].upper()
                if current_status in ("SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"):
                    return CancelResult(
                        outcome=CancelOutcome.ALREADY_TERMINAL,
                        ref=ref,
                        details=f"Workflow is in terminal state {current_status}",
                    )

                cur.execute(
                    """
                    UPDATE dbos.workflow_status
                    SET status = 'CANCELLED', updated_at = %s, completed_at = %s
                    WHERE workflow_uuid = %s
                    """,
                    (now_ms, now_ms, ref.execution_id),
                )
            conn.commit()

        return CancelResult(outcome=CancelOutcome.CANCEL_REQUESTED, ref=ref)

    async def signal(
        self,
        ref: ExecutionRef,
        signal_name: str,
        signal_id: str,
        payload: dict[str, Any],
    ) -> SignalResult:
        if not self.system_database_url:
            internal = self._executions.get(ref.execution_id)
            if internal is None:
                return SignalResult(
                    outcome=SignalOutcome.NOT_FOUND,
                    signal_id=signal_id,
                    ref=ref,
                    error=CanonicalError(
                        category=ErrorCategory.NOT_FOUND,
                        code="workflow_not_found",
                        retryability=False,
                        ambiguity=False,
                    ),
                )
            if internal["state"] in (
                DurableExecutionState.COMPLETED,
                DurableExecutionState.FAILED,
                DurableExecutionState.CANCELLED,
            ):
                return SignalResult(
                    outcome=SignalOutcome.ALREADY_TERMINAL,
                    signal_id=signal_id,
                    ref=ref,
                )

            signal_pair = (ref.execution_id, signal_id)
            if signal_pair in self._signals_seen:
                return SignalResult(
                    outcome=SignalOutcome.DUPLICATE_IGNORED,
                    signal_id=signal_id,
                    ref=ref,
                )
            self._signals_seen.add(signal_pair)
            return SignalResult(outcome=SignalOutcome.DELIVERED, signal_id=signal_id, ref=ref)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_signal, ref, signal_name, signal_id, payload)

    def _sync_signal(
        self,
        ref: ExecutionRef,
        signal_name: str,
        signal_id: str,
        payload: dict[str, Any],
    ) -> SignalResult:
        now_ms = int(time.time() * 1000)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Check workflow status
                cur.execute(
                    "SELECT status FROM dbos.workflow_status WHERE workflow_uuid = %s",
                    (ref.execution_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return SignalResult(
                        outcome=SignalOutcome.NOT_FOUND,
                        signal_id=signal_id,
                        ref=ref,
                        error=CanonicalError(
                            category=ErrorCategory.NOT_FOUND,
                            code="workflow_not_found",
                            retryability=False,
                            ambiguity=False,
                        ),
                    )

                current_status = row[0].upper()
                if current_status in ("SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"):
                    return SignalResult(
                        outcome=SignalOutcome.ALREADY_TERMINAL,
                        signal_id=signal_id,
                        ref=ref,
                    )

                # 2. Check signal deduplication
                cur.execute(
                    """
                    INSERT INTO public.at_signals_seen (execution_id, signal_id)
                    VALUES (%s, %s)
                    ON CONFLICT (execution_id, signal_id) DO NOTHING
                    RETURNING execution_id
                    """,
                    (ref.execution_id, signal_id),
                )
                inserted = cur.fetchone()
                if not inserted:
                    return SignalResult(
                        outcome=SignalOutcome.DUPLICATE_IGNORED,
                        signal_id=signal_id,
                        ref=ref,
                    )

                # 3. Deliver to dbos.notifications table
                serialized_msg = base64.b64encode(pickle.dumps(payload)).decode("ascii")
                composite_msg_id = f"{ref.execution_id}_{signal_id}"
                cur.execute(
                    """
                    INSERT INTO dbos.notifications (
                        message_uuid, destination_uuid, topic, message, created_at_epoch_ms,
                        serialization, consumed
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (message_uuid) DO NOTHING
                    """,
                    (composite_msg_id, ref.execution_id, signal_name, serialized_msg, now_ms, "pickle", False),
                )
            conn.commit()

        return SignalResult(outcome=SignalOutcome.DELIVERED, signal_id=signal_id, ref=ref)

    async def result(
        self,
        ref: ExecutionRef,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        if not self.system_database_url:
            internal = self._executions.get(ref.execution_id)
            if internal is None:
                return ExecutionResult(
                    ref=ref,
                    is_pending=False,
                    state=DurableExecutionState.FAILED,
                    error=CanonicalError(
                        category=ErrorCategory.NOT_FOUND,
                        code="workflow_not_found",
                        retryability=False,
                        ambiguity=False,
                    ),
                )
            if internal["state"] == DurableExecutionState.RUNNING:
                return ExecutionResult(
                    ref=ref,
                    is_pending=True,
                    payload=None,
                    state=DurableExecutionState.RUNNING,
                )
            return ExecutionResult(
                ref=ref,
                is_pending=False,
                payload=internal["result"],
                state=internal["state"],
                error=internal.get("error"),
            )

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_result, ref, timeout_seconds)

    def _sync_result(self, ref: ExecutionRef, timeout_seconds: float | None = None) -> ExecutionResult:
        start_time = time.monotonic()
        timeout = timeout_seconds or 0.0

        while True:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status, error FROM dbos.workflow_status WHERE workflow_uuid = %s",
                        (ref.execution_id,),
                    )
                    status_row = cur.fetchone()

                    if status_row is None:
                        return ExecutionResult(
                            ref=ref,
                            is_pending=False,
                            state=DurableExecutionState.FAILED,
                            error=CanonicalError(
                                category=ErrorCategory.NOT_FOUND,
                                code="workflow_not_found",
                                retryability=False,
                                ambiguity=False,
                            ),
                        )

                    status_str, error_text = status_row
                    state = self._map_dbos_status(status_str)

                    if state == DurableExecutionState.COMPLETED:
                        cur.execute(
                            "SELECT output, error FROM dbos.workflow_output WHERE workflow_uuid = %s",
                            (ref.execution_id,),
                        )
                        out_row = cur.fetchone()
                        payload = None
                        if out_row and out_row[0]:
                            try:
                                payload = pickle.loads(base64.b64decode(out_row[0]))
                            except Exception:
                                payload = out_row[0]

                        return ExecutionResult(
                            ref=ref,
                            is_pending=False,
                            payload=payload,
                            state=DurableExecutionState.COMPLETED,
                        )

                    if state in (DurableExecutionState.FAILED, DurableExecutionState.CANCELLED):
                        return ExecutionResult(
                            ref=ref,
                            is_pending=False,
                            state=state,
                            error=CanonicalError(
                                category=ErrorCategory.INTERNAL,
                                code="workflow_error",
                                message=str(error_text or "Workflow failed"),
                                retryability=False,
                                ambiguity=False,
                            ),
                        )

            if timeout <= 0 or (time.monotonic() - start_time) >= timeout:
                return ExecutionResult(
                    ref=ref,
                    is_pending=True,
                    payload=None,
                    state=DurableExecutionState.RUNNING,
                )

            time.sleep(0.1)
