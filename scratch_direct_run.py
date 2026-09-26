import os, json, sys
os.environ["AT_TEST_POSTGRES_URL"] = "postgresql:///at_dbos_probe"
os.environ["AT_TEST_FIXTURE_URL"] = "postgresql:///at_external_fixture"
from all_tomorrow.harness.types import HarnessInput, ExecutionIdentity, TraceContext, FailPoint
from uuid import uuid4

run_id = f"test-{uuid4()}"
payload = {
    "input": HarnessInput(
        task_name="t", query_item_id="i", mutation_key=f"m-{run_id}", mutation_value="v",
        injected_fail_point=FailPoint.BEFORE_MODEL_RESULT_PERSIST
    ).model_dump(mode="json"),
    "identity": ExecutionIdentity(work_id="w", run_id=run_id).model_dump(mode="json"),
    "trace": TraceContext(trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}").model_dump(mode="json"),
}
os.environ["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
os.environ["AT_TEST_COMMON_PHASE"] = "crash"

print("Importing walking_skeleton_worker...", flush=True)
from tests.support import walking_skeleton_worker
print("Calling main...", flush=True)
walking_skeleton_worker.main()
