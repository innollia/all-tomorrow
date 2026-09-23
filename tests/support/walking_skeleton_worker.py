"""Real independent worker process for Walking Skeleton scenarios (C-01, C-02, C-03, etc.).

Runs:
PydanticAI agent → LiteLLM / fixture → DBOS step / workflow → mutation fixture
Supports distinct injected failure points:
- BEFORE_MODEL_CALL (exit 78)
- AFTER_MUTATION_SIDE_EFFECT (exit 77)
- WHILE_WAITING_USER (wait for signal and output marker)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

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
    DBOS(config={
        "name": "all-tomorrow-walking-skeleton-worker",
        "system_database_url": os.environ["AT_TEST_POSTGRES_URL"],
        "application_version": "ws-v1",
    })
    try:
        DBOS.launch()
        identity = ExecutionIdentity.model_validate(payload["identity"])
        workflow_id = f"{identity.work_id}:{identity.run_id}"
        phase = os.environ.get("AT_TEST_COMMON_PHASE", "normal")

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

        with SetWorkflowID(workflow_id):
            output = run(payload)
        write_output(output)
    finally:
        DBOS.destroy(destroy_registry=True)


if __name__ == "__main__":
    main()
