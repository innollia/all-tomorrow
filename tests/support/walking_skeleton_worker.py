"""Real independent worker process for Walking Skeleton scenarios (C-01, C-02, C-03, C-04, C-05, C-07).

Runs:
PydanticAI agent → LiteLLM / fixture → DBOS step / workflow → mutation fixture
Supports distinct injected failure points:
- BEFORE_MODEL_CALL (exit 78)
- AFTER_MUTATION_SIDE_EFFECT (exit 77)
- WHILE_WAITING_USER (wait for signal and output marker)
- C-04: Commit Run STARTING then crash (exit 75) before external start
- C-05: External start in DBOS then crash (exit 76) before local ref attach
- C-07: Hang worker past timeout
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import psycopg
from dbos import DBOS, SetWorkflowID

from all_tomorrow.harness.types import ExecutionIdentity, FailPoint, HarnessInput, HarnessOutput, TraceContext
from tests.support.live_common import (
    apply_mutation,
    crash_at,
    emit_trace,
    model_agent,
    model_context,
    observe_model,
    record_followup,
    transient_model_error,
)
from tests.support.otel_file_exporter import tracer_for

TRACER = tracer_for(os.environ["AT_TEST_OTEL_SPANS"]) if os.environ.get("AT_TEST_OTEL_SPANS") else None


def write_output(output: dict) -> None:
    encoded = json.dumps(output, sort_keys=True)
    if path := os.environ.get("AT_TEST_COMMON_RESULT_PATH"):
        Path(path).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, flush=True)


@DBOS.step(name="ws_model_decision", retries_allowed=True, max_attempts=5, interval_seconds=1, backoff_rate=1, should_retry=transient_model_error)
def decide(payload: dict) -> dict:
    data = HarnessInput.model_validate(payload["input"])
    trace = TraceContext.model_validate(payload["trace"])
    task_name, item_id = data.task_name, data.query_item_id

    # Injected crash point: BEFORE_MODEL_RESULT_PERSIST
    crash_at(data, FailPoint.BEFORE_MODEL_RESULT_PERSIST, 78, TRACER, trace)

    with model_context(trace):
        result = model_agent().run_sync(
            f"Evaluate task '{task_name}' for item '{item_id}'"
        )
    observe_model(os.environ["AT_TEST_FIXTURE_URL"], data)
    return result.output.model_dump()


@DBOS.step(name="ws_mutation")
def mutate(payload: dict) -> str:
    parsed = HarnessInput.model_validate(payload["input"])
    trace = TraceContext.model_validate(payload["trace"])
    value = apply_mutation(os.environ["AT_TEST_FIXTURE_URL"], parsed)
    # Injected crash point: AFTER_MUTATION_SIDE_EFFECT
    crash_at(parsed, FailPoint.AFTER_MUTATION_SIDE_EFFECT, 77, TRACER, trace)
    return value


@DBOS.workflow(name="ws_workflow")
def run(payload: dict) -> dict:
    data = HarnessInput.model_validate(payload["input"])
    identity = ExecutionIdentity.model_validate(payload["identity"])
    trace = TraceContext.model_validate(payload["trace"])

    decision = decide(payload)
    crash_at(data, FailPoint.AFTER_MODEL_RESULT_PERSIST, 79, TRACER, trace)

    value = mutate(payload)
    signal_payload = None

    if data.wait_for_signal_name:
        DBOS.set_event("ws_waiting", True)
        emit_trace(TRACER, trace, "ws_dbos_wait_started")
        # In a test, wait for external signal
        signal_payload = DBOS.recv(topic=data.wait_for_signal_name, timeout_seconds=45)
        emit_trace(TRACER, trace, "ws_dbos_recovered")

    emit_trace(TRACER, trace, "ws_completed")
    return HarnessOutput(
        task_name=data.task_name,
        read_item_data={"item_id": data.query_item_id, "stock": 42},
        model_decision=decision,
        mutation_committed=True,
        mutation_value=value,
        signal_received_payload=signal_payload,
        correlation_id=trace.correlation_id,
        execution_identity=identity,
        timer_elapsed_seconds=data.timer_delay_seconds,
    ).model_dump(mode="json")


def main() -> None:
    payload = json.loads(os.environ["AT_TEST_COMMON_PAYLOAD"])
    phase = os.environ.get("AT_TEST_COMMON_PHASE", "normal")
    identity = ExecutionIdentity.model_validate(payload["identity"])

    if phase == "c07_hang":
        print(f"hanging_worker_pid={os.getpid()}", flush=True)
        while True:
            time.sleep(1)

    if phase == "c04_crash":
        with psycopg.connect(os.environ["AT_TEST_POSTGRES_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.at_runs (
                        run_id TEXT PRIMARY KEY,
                        work_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        execution_ref JSONB,
                        attempt_number INT NOT NULL DEFAULT 1,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    INSERT INTO public.at_runs (run_id, work_id, status, execution_ref, attempt_number)
                    VALUES (%s, %s, 'STARTING', NULL, 1)
                    ON CONFLICT (run_id) DO UPDATE SET status = 'STARTING'
                    """,
                    (identity.run_id, identity.work_id),
                )
            conn.commit()
        print(f"c04_barrier_starting_pid={os.getpid()}", flush=True)
        os._exit(75)

    DBOS(config={
        "name": "all-tomorrow-walking-skeleton-worker",
        "system_database_url": os.environ["AT_TEST_POSTGRES_URL"],
        "application_version": "ws-v1",
    })
    try:
        DBOS.launch()
        workflow_id = f"{identity.work_id}:{identity.run_id}"

        if phase == "wait":
            with SetWorkflowID(workflow_id):
                DBOS.start_workflow(run, payload)
            for _ in range(100):
                if DBOS.get_event(workflow_id, "ws_waiting", timeout_seconds=0.1):
                    print(f"waiting_pid={os.getpid()}", flush=True)
                    while True:
                        time.sleep(1)
                time.sleep(0.1)
            raise RuntimeError("Walking skeleton workflow did not reach wait")

        if phase == "signal":
            DBOS.send(workflow_id, {"approved": True}, topic="approval")
            return

        if phase == "recover":
            output = DBOS.retrieve_workflow(workflow_id).get_result()
            write_output(output)
            return

        if phase == "resume":
            topic = HarnessInput.model_validate(payload["input"]).wait_for_signal_name or "approval"
            DBOS.send(workflow_id, {"approved": True}, topic=topic)
            output = DBOS.retrieve_workflow(workflow_id).get_result()
            print(f"resumed_pid={os.getpid()}", flush=True)
            write_output(output)
            return

        if phase == "c04_reconcile":
            from all_tomorrow.adapters.dbos_adapter import DBOSDurableAdapter
            from all_tomorrow.delivery import DeliveryReconciler, DeliveryRecord, DeliveryKind, format_idempotency_key
            adapter = DBOSDurableAdapter(system_database_url=os.environ["AT_TEST_POSTGRES_URL"])
            reconciler = DeliveryReconciler(adapter)
            delivery = DeliveryRecord(
                delivery_id=f"dlv_{identity.run_id}",
                kind=DeliveryKind.RUN_START,
                subject_refs={"run_id": identity.run_id, "work_id": identity.work_id},
                destination_adapter="dbos",
                idempotency_key=format_idempotency_key("run", "start", identity.run_id),
                payload={"workflow_name": "ws_workflow", "workflow_payload": payload},
            )
            asyncio.run(reconciler.reconcile(delivery))
            ref = asyncio.run(adapter.find_by_run_id(identity.run_id))
            ref_dict = {
                "backend": ref.backend,
                "execution_id": ref.execution_id,
                "execution_version": ref.execution_version,
                "attached_at": ref.attached_at.isoformat() if ref.attached_at else None,
                "metadata": ref.metadata,
            } if ref else None
            with psycopg.connect(os.environ["AT_TEST_POSTGRES_URL"]) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.at_runs
                        SET status = 'RUNNING', execution_ref = %s, updated_at = NOW()
                        WHERE run_id = %s
                        """,
                        (psycopg.types.json.Jsonb(ref_dict) if ref_dict else None, identity.run_id),
                    )
                conn.commit()
            print(f"c04_reconciled_pid={os.getpid()} execution_id={ref.execution_id if ref else None}", flush=True)
            return

        if phase == "c05_crash":
            exec_id = f"dbos_{identity.run_id}"
            with psycopg.connect(os.environ["AT_TEST_POSTGRES_URL"]) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS public.at_runs (
                            run_id TEXT PRIMARY KEY,
                            work_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            execution_ref JSONB,
                            attempt_number INT NOT NULL DEFAULT 1,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        """
                        INSERT INTO public.at_runs (run_id, work_id, status, execution_ref, attempt_number)
                        VALUES (%s, %s, 'STARTING', NULL, 1)
                        ON CONFLICT (run_id) DO UPDATE SET status = 'STARTING'
                        """,
                        (identity.run_id, identity.work_id),
                    )
                conn.commit()
            with SetWorkflowID(exec_id):
                DBOS.start_workflow(run, payload)
            # Barrier: external start exists in DBOS, but execution_ref is NOT attached in at_runs!
            print(f"c05_barrier_external_started_pid={os.getpid()}", flush=True)
            os._exit(76)

        if phase == "c05_reconcile":
            from all_tomorrow.adapters.dbos_adapter import DBOSDurableAdapter
            from all_tomorrow.delivery import DeliveryReconciler, DeliveryRecord, DeliveryKind, format_idempotency_key
            adapter = DBOSDurableAdapter(system_database_url=os.environ["AT_TEST_POSTGRES_URL"])
            reconciler = DeliveryReconciler(adapter)
            delivery = DeliveryRecord(
                delivery_id=f"dlv_{identity.run_id}",
                kind=DeliveryKind.RUN_START,
                subject_refs={"run_id": identity.run_id, "work_id": identity.work_id},
                destination_adapter="dbos",
                idempotency_key=format_idempotency_key("run", "start", identity.run_id),
                payload={"workflow_name": "ws_workflow", "workflow_payload": payload},
            )
            asyncio.run(reconciler.reconcile(delivery))
            ref = asyncio.run(adapter.find_by_run_id(identity.run_id))
            ref_dict = {
                "backend": ref.backend,
                "execution_id": ref.execution_id,
                "execution_version": ref.execution_version,
                "attached_at": ref.attached_at.isoformat() if ref.attached_at else None,
                "metadata": ref.metadata,
            } if ref else None
            with psycopg.connect(os.environ["AT_TEST_POSTGRES_URL"]) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.at_runs
                        SET status = 'RUNNING', execution_ref = %s, updated_at = NOW()
                        WHERE run_id = %s
                        """,
                        (psycopg.types.json.Jsonb(ref_dict) if ref_dict else None, identity.run_id),
                    )
                conn.commit()
            print(f"c05_reconciled_pid={os.getpid()} execution_id={ref.execution_id if ref else None}", flush=True)
            return

        with SetWorkflowID(workflow_id):
            output = run(payload)
        write_output(output)
    finally:
        DBOS.destroy(destroy_registry=True)


if __name__ == "__main__":
    main()
