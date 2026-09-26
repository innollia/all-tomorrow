import os
import sys

os.environ["AT_TEST_POSTGRES_URL"] = "postgresql:///at_dbos_probe"
os.environ["AT_TEST_FIXTURE_URL"] = "postgresql:///at_external_fixture"
os.environ["AT_TEST_COMMON_PHASE"] = "crash"

from dbos import DBOS, SetWorkflowID
from all_tomorrow.harness.types import HarnessInput, FailPoint
from tests.support.live_common import crash_at

@DBOS.step(name="s")
def step_fn(payload):
    print("step_fn entered!", flush=True)
    data = HarnessInput.model_validate(payload["input"])
    crash_at(data, FailPoint.BEFORE_MODEL_RESULT_PERSIST, 78, None, None)
    return "ok"

@DBOS.workflow(name="w")
def wf(payload):
    print("wf entered!", flush=True)
    return step_fn(payload)

DBOS(config={"name": "test-app", "system_database_url": os.environ["AT_TEST_POSTGRES_URL"]})
DBOS.launch()
with SetWorkflowID("test-wf-step-crash"):
    wf({"input": {"task_name": "t", "query_item_id": "i", "mutation_key": "m", "mutation_value": "v", "injected_fail_point": "before_model_result_persist"}})
