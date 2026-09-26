import json
import os
import sys
from uuid import uuid4
from all_tomorrow.harness.types import HarnessInput, ExecutionIdentity, TraceContext
from tests.support.walking_skeleton_worker import main

run_id = f"c01-{uuid4()}"
work_id = "work-c01"
mutation_key = f"mut-{run_id}"

payload = {
    "input": HarnessInput(
        task_name="Check inventory",
        query_item_id="item-01",
        mutation_key=mutation_key,
        mutation_value="c01-val",
    ).model_dump(mode="json"),
    "identity": ExecutionIdentity(work_id=work_id, run_id=run_id).model_dump(mode="json"),
    "trace": TraceContext(
        trace_id=uuid4().hex, span_id=uuid4().hex[:16], correlation_id=f"corr-{run_id}"
    ).model_dump(mode="json"),
}

os.environ["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
os.environ["AT_TEST_POSTGRES_URL"] = "postgresql:///at_dbos_probe"
os.environ["AT_TEST_FIXTURE_URL"] = "postgresql:///at_external_fixture"
os.environ["AT_TEST_COMMON_PHASE"] = "normal"
os.environ["AT_TEST_OTEL_SPANS"] = "/tmp/test-spans.jsonl"

print("calling main() directly...")
main()
print("main() returned successfully!")
