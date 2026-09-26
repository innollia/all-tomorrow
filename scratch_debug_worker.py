import json
import os
import subprocess
import sys
from uuid import uuid4
from all_tomorrow.harness.types import HarnessInput, ExecutionIdentity, TraceContext, FailPoint

run_id = f"test-{uuid4()}"
payload = {
    "input": HarnessInput(
        task_name="t", query_item_id="i", mutation_key=f"m-{run_id}", mutation_value="v",
        injected_fail_point=FailPoint.BEFORE_MODEL_RESULT_PERSIST
    ).model_dump(mode="json"),
    "identity": ExecutionIdentity(work_id="w", run_id=run_id).model_dump(mode="json"),
    "trace": TraceContext(trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}").model_dump(mode="json"),
}
env = os.environ.copy()
env["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
env["AT_TEST_COMMON_PHASE"] = "crash"
proc = subprocess.run([sys.executable, "-m", "tests.support.walking_skeleton_worker"], env=env, capture_output=True, text=True, timeout=15)
print("returncode:", proc.returncode)
print("stdout:", proc.stdout)
print("stderr:", proc.stderr)
