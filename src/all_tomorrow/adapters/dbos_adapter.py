from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any, Callable

from dbos import DBOS, SetWorkflowID
from dbos._error import DBOSNonExistentWorkflowError

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


_WORKFLOW_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_dbos_workflow(name: str, fn: Callable[..., Any]) -> None:
    _WORKFLOW_REGISTRY[name] = fn


@DBOS.workflow(name="at_generic_workflow")
def at_generic_workflow(payload: dict[str, Any]) -> Any:
    wait_topic = payload.get("wait_for_signal") or payload.get("wait_topic")
    if wait_topic:
        timeout = payload.get("wait_timeout_seconds", 60)
        return DBOS.recv(topic=wait_topic, timeout_seconds=timeout)
    return payload.get("result", payload)


@DBOS.workflow(name="walking_skeleton_workflow")
def at_walking_skeleton_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    topic = payload.get("wait_for_signal") or payload.get("wait_topic") or "user_response"
    timeout = payload.get("wait_timeout_seconds", 120)
    sig = DBOS.recv(topic=topic, timeout_seconds=timeout)
    return {
        "status": "resumed",
        "signal": sig,
        "input_payload": payload,
    }


_WORKFLOW_REGISTRY["walking_skeleton_workflow"] = at_walking_skeleton_workflow
_WORKFLOW_REGISTRY["at_generic_workflow"] = at_generic_workflow
_WORKFLOW_REGISTRY["wf_concurrent"] = at_generic_workflow
_WORKFLOW_REGISTRY["test_workflow"] = at_generic_workflow
_WORKFLOW_REGISTRY["wf_test"] = at_generic_workflow
_WORKFLOW_REGISTRY["wf"] = at_generic_workflow


_DBOS_LAUNCH_LOCK = threading.Lock()
_CURRENT_LAUNCHED_DBOS_URL: str | None = None


class DBOSDurableAdapter(DurableExecutionPort):
    """DBOS implementation of DurableExecutionPort backed by real DBOS SDK and PostgreSQL.

    Strict DBOS ownership boundary:
    1. NEVER creates, inserts into, queries, or updates dbos.* internal system tables.
       Workflow status, result, signal, and cancellation are performed strictly through
       DBOS public SDK API (`DBOS.get_workflow_status()`, `DBOS.cancel_workflow()`,
       `DBOS.send()`, `DBOS.retrieve_workflow()`).
    2. Lifecycle is managed strictly via public DBOS SDK APIs (`DBOS(config=...)`,
       `DBOS.launch()`, `DBOS.destroy()`) without querying private globals or configs.
    3. Only application-owned mappings (such as `public.at_run_executions` and
       `public.at_signals_seen`) are managed in application schema.
    4. Lifecycle operations never swallow destruction errors.
    """

    @classmethod
    def destroy_runtime(cls) -> None:
        """Cleanly shut down DBOS runtime. Never silences destruction errors."""
        global _CURRENT_LAUNCHED_DBOS_URL
        with _DBOS_LAUNCH_LOCK:
            DBOS.destroy()
            _CURRENT_LAUNCHED_DBOS_URL = None

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

        self._db_initialized: bool = False

    def _ensure_db_initialized(self) -> None:
        """Create application-owned schema tables. Fails fast without swallowing errors."""
        if self._db_initialized or not self.system_database_url:
            return
        self._init_db()
        self._db_initialized = True

    def _ensure_dbos_launched(self) -> None:
        """Ensure DBOS SDK runtime is launched with configured database URL via public SDK APIs.

        Boundary:
        - Uses strictly public DBOS(config=...) and DBOS.launch().
        - If database URL changes, cleans up previous instance via DBOS.destroy().
        - Never silences destruction errors.
        - Does not access private dbos._dbos or inspect internal private attributes.
        """
        global _CURRENT_LAUNCHED_DBOS_URL
        if not self.system_database_url:
            return
        with _DBOS_LAUNCH_LOCK:
            if _CURRENT_LAUNCHED_DBOS_URL is not None:
                if _CURRENT_LAUNCHED_DBOS_URL == self.system_database_url:
                    return
                # Different database URL requested; destroy current DBOS instance
                DBOS.destroy()
                _CURRENT_LAUNCHED_DBOS_URL = None

            DBOS(config={
                "name": self.application_name,
                "system_database_url": self.system_database_url,
            })
            DBOS.launch()
            _CURRENT_LAUNCHED_DBOS_URL = self.system_database_url

    def _get_connection(self):
        import psycopg

        if not self.system_database_url:
            raise RuntimeError("No system_database_url configured for DBOS adapter")
        return psycopg.connect(self.system_database_url)

    def _init_db(self) -> None:
        """Create application-owned schema tables. Fails fast without swallowing errors."""
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
        self._ensure_db_initialized()
        self._ensure_dbos_launched()
        exec_id = f"dbos_{run_key}"

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Store application-owned mapping only! No touching dbos.* tables!
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
            conn.commit()

        # Check if DBOS workflow is already running or has been started
        status_obj = DBOS.get_workflow_status(actual_exec_id)
        if status_obj is None:
            wf_fn = _WORKFLOW_REGISTRY.get(workflow_name) or at_generic_workflow
            with SetWorkflowID(actual_exec_id):
                DBOS.start_workflow(wf_fn, payload)

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
                        safe_message=f"Workflow '{ref.execution_id}' not found",
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
        try:
            self._ensure_dbos_launched()
            status_obj = DBOS.get_workflow_status(ref.execution_id)
        except Exception as e:
            return ExecutionStatusResult(
                ref=ref,
                state=DurableExecutionState.FAILED,
                error=normalize_exception(e, default_code="backend_unavailable"),
            )

        if status_obj is None:
            return ExecutionStatusResult(
                ref=ref,
                state=DurableExecutionState.PENDING,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="workflow_not_found",
                    retryability=False,
                    ambiguity=False,
                    safe_message=f"Workflow '{ref.execution_id}' not found",
                ),
            )

        state = self._map_dbos_status(status_obj.status)
        canonical_error = None
        if status_obj.error:
            canonical_error = CanonicalError(
                category=ErrorCategory.UNAVAILABLE,
                code="workflow_error",
                retryability=False,
                ambiguity=False,
                safe_message=str(status_obj.error),
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
        self._ensure_db_initialized()
        # Strictly queries public.at_run_executions! Never touches dbos.* tables!
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT execution_id, created_at FROM public.at_run_executions WHERE run_id = %s",
                    (run_key,),
                )
                row = cur.fetchone()
                if row is None:
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
                        safe_message=f"Workflow '{ref.execution_id}' not found",
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
        try:
            self._ensure_dbos_launched()
            status_obj = DBOS.get_workflow_status(ref.execution_id)
        except Exception as e:
            return CancelResult(
                outcome=CancelOutcome.FAILED,
                ref=ref,
                error=normalize_exception(e, default_code="backend_unavailable"),
            )
        if status_obj is None:
            return CancelResult(
                outcome=CancelOutcome.NOT_FOUND,
                ref=ref,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="workflow_not_found",
                    retryability=False,
                    ambiguity=False,
                    safe_message=f"Workflow '{ref.execution_id}' not found",
                ),
            )

        current_status = status_obj.status.upper()
        if current_status in ("SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"):
            return CancelResult(
                outcome=CancelOutcome.ALREADY_TERMINAL,
                ref=ref,
                details=f"Workflow is in terminal state {current_status}",
            )

        # Use DBOS public API for cancellation
        DBOS.cancel_workflow(ref.execution_id)
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
                        safe_message=f"Workflow '{ref.execution_id}' not found",
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
        try:
            self._ensure_db_initialized()
            self._ensure_dbos_launched()
            # 1. Check workflow status via public SDK
            status_obj = DBOS.get_workflow_status(ref.execution_id)
        except Exception as e:
            return SignalResult(
                outcome=SignalOutcome.FAILED,
                signal_id=signal_id,
                ref=ref,
                error=normalize_exception(e, default_code="backend_unavailable"),
            )
        if status_obj is None:
            return SignalResult(
                outcome=SignalOutcome.NOT_FOUND,
                signal_id=signal_id,
                ref=ref,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="workflow_not_found",
                    retryability=False,
                    ambiguity=False,
                    safe_message=f"Workflow '{ref.execution_id}' not found",
                ),
            )

        current_status = status_obj.status.upper()
        if current_status in ("SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"):
            return SignalResult(
                outcome=SignalOutcome.ALREADY_TERMINAL,
                signal_id=signal_id,
                ref=ref,
            )

        # 2. Check if signal was already recorded as delivered in application-owned table
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM public.at_signals_seen WHERE execution_id = %s AND signal_id = %s",
                    (ref.execution_id, signal_id),
                )
                if cur.fetchone() is not None:
                    return SignalResult(
                        outcome=SignalOutcome.DUPLICATE_IGNORED,
                        signal_id=signal_id,
                        ref=ref,
                    )

        # 3. Deliver signal via DBOS.send() public API with idempotency_key
        try:
            DBOS.send(ref.execution_id, payload, topic=signal_name, idempotency_key=signal_id)
        except DBOSNonExistentWorkflowError:
            return SignalResult(
                outcome=SignalOutcome.NOT_FOUND,
                signal_id=signal_id,
                ref=ref,
                error=CanonicalError(
                    category=ErrorCategory.NOT_FOUND,
                    code="workflow_not_found",
                    retryability=False,
                    ambiguity=False,
                    safe_message=f"Workflow '{ref.execution_id}' non-existent in DBOS",
                ),
            )
        except Exception as e:
            return SignalResult(
                outcome=SignalOutcome.FAILED,
                signal_id=signal_id,
                ref=ref,
                error=normalize_exception(e, default_code="signal_send_failed"),
            )

        # 4. Record successful delivery in application-owned table
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.at_signals_seen (execution_id, signal_id, delivered_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (execution_id, signal_id) DO NOTHING
                    """,
                    (ref.execution_id, signal_id),
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
                        safe_message=f"Workflow '{ref.execution_id}' not found",
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
        try:
            self._ensure_dbos_launched()
        except Exception as e:
            return ExecutionResult(
                ref=ref,
                is_pending=False,
                state=DurableExecutionState.FAILED,
                error=normalize_exception(e, default_code="backend_unavailable"),
            )
        start_time = time.monotonic()
        timeout = timeout_seconds or 0.0

        while True:
            try:
                status_obj = DBOS.get_workflow_status(ref.execution_id)
            except Exception as e:
                return ExecutionResult(
                    ref=ref,
                    is_pending=False,
                    state=DurableExecutionState.FAILED,
                    error=normalize_exception(e, default_code="backend_unavailable"),
                )
            if status_obj is None:
                return ExecutionResult(
                    ref=ref,
                    is_pending=False,
                    state=DurableExecutionState.FAILED,
                    error=CanonicalError(
                        category=ErrorCategory.NOT_FOUND,
                        code="workflow_not_found",
                        retryability=False,
                        ambiguity=False,
                        safe_message=f"Workflow '{ref.execution_id}' not found",
                    ),
                )

            state = self._map_dbos_status(status_obj.status)

            if state == DurableExecutionState.COMPLETED:
                return ExecutionResult(
                    ref=ref,
                    is_pending=False,
                    payload=status_obj.output,
                    state=DurableExecutionState.COMPLETED,
                )

            if state in (DurableExecutionState.FAILED, DurableExecutionState.CANCELLED):
                return ExecutionResult(
                    ref=ref,
                    is_pending=False,
                    state=state,
                    error=CanonicalError(
                        category=ErrorCategory.UNAVAILABLE if state == DurableExecutionState.FAILED else ErrorCategory.INVALID_STATE,
                        code="workflow_failed" if state == DurableExecutionState.FAILED else "workflow_cancelled",
                        safe_message=str(status_obj.error or f"Workflow {state.value}"),
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
