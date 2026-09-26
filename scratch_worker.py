import json
import os
import sys
from all_tomorrow.harness.types import HarnessInput, ExecutionIdentity, TraceContext
from tests.support.walking_skeleton_worker import main

payload = {
    "input": HarnessInput(
        task_name="Check inventory",
        query_item_id="item-01",
        mutation_key="mut-test",
        mutation_value="val-test",
    ).model_dump(mode="json"),
    "identity": ExecutionIdentity(work_id="work-test", run_id="run-test").model_dump(mode="json"),
    "trace": TraceContext(
        trace_id="0"*32, span_id="0"*16, correlation_id="corr-test"
    ).model_dump(mode="json"),
}

os.environ["AT_TEST_COMMON_PAYLOAD"] = json.dumps(payload)
os.environ["AT_TEST_POSTGRES_URL"] = "postgresql:///at_dbos_probe"
os.environ["AT_TEST_FIXTURE_URL"] = "postgresql:///at_external_fixture"
os.environ["AT_TEST_COMMON_PHASE"] = "normal"

print("calling main() directly...")
main()
print("main() returned successfully!")
