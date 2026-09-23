"""Real DBOS D01 worker using the same typed input/output as Restate."""

import json
import os
import time
from pathlib import Path

from dbos import DBOS, SetWorkflowID

from all_tomorrow.harness.agent import create_deterministic_agent
from all_tomorrow.harness.tools import read_inventory_tool
from all_tomorrow.harness.types import ExecutionIdentity, FailPoint, HarnessInput, HarnessOutput, TraceContext
from .live_common import apply_mutation, observe_model, crash_at, emit_trace, record_followup, model_agent, model_context, transient_model_error
from .otel_file_exporter import persisted_context, tracer_for


TRACER = tracer_for(os.environ["AT_TEST_OTEL_SPANS"]) if os.environ.get("AT_TEST_OTEL_SPANS") else None


def write_output(output):
    encoded = json.dumps(output, sort_keys=True)
    if path := os.environ.get("AT_TEST_COMMON_RESULT_PATH"):
        Path(path).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, flush=True)


@DBOS.step(name="common_read_inventory")
def read(item_id: str) -> dict:
    return read_inventory_tool(item_id)


@DBOS.step(name="common_model_decision", retries_allowed=True, max_attempts=6, interval_seconds=2, backoff_rate=1, should_retry=transient_model_error)
def decide(payload: dict) -> dict:
    data = HarnessInput.model_validate(payload["input"])
    trace = TraceContext.model_validate(payload["trace"])
    task_name, item_id = data.task_name, data.query_item_id
    with model_context(trace):
        result = model_agent().run_sync(
            f"Evaluate task '{task_name}' for item '{item_id}'"
        )
    observe_model(os.environ["AT_TEST_FIXTURE_URL"], data)
    crash_at(data, FailPoint.BEFORE_MODEL_RESULT_PERSIST, 78, TRACER, trace)
    return result.output.model_dump()


@DBOS.step(name="common_mutation")
def mutate(payload: dict) -> str:
    parsed = HarnessInput.model_validate(payload["input"])
    trace = TraceContext.model_validate(payload["trace"])
    value = apply_mutation(os.environ["AT_TEST_FIXTURE_URL"], parsed)
    crash_at(parsed, FailPoint.AFTER_MUTATION_SIDE_EFFECT, 77, TRACER, trace)
    return value


@DBOS.step(name="common_followup")
def followup(key: str):
    record_followup(os.environ["AT_TEST_FIXTURE_URL"], key)


@DBOS.step(name="common_v2_finalize")
def finalize(key: str):
    from .common_revision_v2 import finalize as implementation
    return implementation(os.environ["AT_TEST_FIXTURE_URL"], key)


@DBOS.workflow(name="common_d01_workflow")
def run(payload: dict) -> dict:
    data = HarnessInput.model_validate(payload["input"])
    identity = ExecutionIdentity.model_validate(payload["identity"])
    trace = TraceContext.model_validate(payload["trace"])
    inventory = read(data.query_item_id)
    decision = decide(payload)
    crash_at(data, FailPoint.AFTER_MODEL_RESULT_PERSIST, 79, TRACER, trace)
    value = mutate(payload)
    signal_payload = None
    if data.timer_delay_seconds:
        emit_trace(TRACER, trace, "common_timer_started")
        DBOS.sleep(data.timer_delay_seconds)
        emit_trace(TRACER, trace, "common_timer_finished")
    if data.wait_for_signal_name:
        DBOS.set_event("common_waiting", True)
        emit_trace(TRACER, trace, "common_dbos_wait_started")
        signal_payload = DBOS.recv(topic=data.wait_for_signal_name, timeout_seconds=45)
        emit_trace(TRACER, trace, "common_dbos_recovered")
    if signal_payload is not None:
        followup(data.mutation_key)
    if os.environ.get("AT_TEST_APP_REVISION") == "2":
        finalize(data.mutation_key)
    emit_trace(TRACER, trace, "common_completed")
    return HarnessOutput(
        task_name=data.task_name,
        read_item_data=inventory,
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
        "name": "all-tomorrow-common-d01",
        "system_database_url": os.environ["AT_TEST_POSTGRES_URL"],
        "application_version": "common-compatible-v1",
    })
    try:
        DBOS.launch()
        identity = ExecutionIdentity.model_validate(payload["identity"])
        workflow_id = f"{identity.work_id}:{identity.run_id}"
        phase = os.environ.get("AT_TEST_COMMON_PHASE", "normal")
        if phase == "start":
            with SetWorkflowID(workflow_id):
                DBOS.start_workflow(run, payload)
            while True:
                time.sleep(1)
        if phase == "signal":
            DBOS.send(workflow_id, {"approved": True}, topic="approval")
            return
        if phase == "cancel":
            DBOS.cancel_workflow(workflow_id)
            print("cancelled", flush=True)
            return
        if phase == "recover":
            output = DBOS.retrieve_workflow(workflow_id).get_result()
            write_output(output)
            return
        if phase == "wait":
            with SetWorkflowID(workflow_id):
                DBOS.start_workflow(run, payload)
            for _ in range(100):
                if DBOS.get_event(workflow_id, "common_waiting", timeout_seconds=0.1):
                    print(f"waiting_pid={os.getpid()}", flush=True)
                    while True:
                        time.sleep(1)
                time.sleep(0.1)
            raise RuntimeError("Common DBOS workflow did not reach wait")
        if phase == "resume":
            topic = HarnessInput.model_validate(payload["input"]).wait_for_signal_name
            assert topic is not None
            DBOS.send(workflow_id, {"approved": True}, topic=topic)
            output = DBOS.retrieve_workflow(workflow_id).get_result()
            print(f"resumed_pid={os.getpid()}", flush=True)
        else:
            with SetWorkflowID(workflow_id):
                output = run(payload)
        write_output(output)
    finally:
        DBOS.destroy(destroy_registry=True)


if __name__ == "__main__":
    main()
