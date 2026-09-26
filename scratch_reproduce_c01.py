import json
import os
import sys
import subprocess
from uuid import uuid4
from all_tomorrow.harness.types import HarnessInput, ExecutionIdentity, TraceContext, FailPoint

run_id = f"c01-sim-{uuid4()}"
work_id = "work-c01"
mutation_key = f"mut-{run_id}"

payload = {
    "input": HarnessInput(
        task_name="Check inventory",
        query_item_id="item-01",
        mutation_key=mutation_key,
        mutation_value="c01-val",
        injected_fail_point=FailPoint.BEFORE_MODEL_RESULT_PERSIST,
    ).model_dump(mode="json"),
    "identity": ExecutionIdentity(work_id=work_id, run_id=run_id).model_dump(mode="json"),
    "trace": TraceContext(
        trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}"
    ).model_dump(mode="json"),
}

env = os.environ.copy()
env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
env["AT_TEST_POSTGRES_URL"] = "postgresql:///at_dbos_probe"
env["AT_TEST_FIXTURE_URL"] = "postgresql:///at_external_fixture"
env["AT_TEST_COMMON_PHASE"] = "crash"
env["AT_TEST_OTEL_SPANS"] = "/tmp/c01-sim-spans.jsonl"

print("1. Running first worker (crash)...")
p1 = subprocess.run([sys.executable, "-m", "tests.support.walking_skeleton_worker"], env=env, capture_output=True, text=True)
print("p1 returncode:", p1.returncode)
print("p1 stdout:", p1.stdout)
print("p1 stderr:", p1.stderr)

print("2. Running second worker (normal)...")
env["AT_TEST_COMMON_PHASE"] = "normal"
p2 = subprocess.run([sys.executable, "-m", "tests.support.walking_skeleton_worker"], env=env, capture_output=True, text=True)
print("p2 returncode:", p2.returncode)
print("p2 stdout:", p2.stdout)
print("p2 stderr:", p2.stderr)
