"""DBOS PydanticAI TestModel crash points around step persistence."""

import os
import sys

import psycopg
from dbos import DBOS, SetWorkflowID

from all_tomorrow.harness.agent import create_deterministic_agent


SYSTEM_URL = os.environ["AT_TEST_POSTGRES_URL"]
FIXTURE_URL = os.environ["AT_TEST_FIXTURE_URL"]
WORKFLOW_ID = os.environ["AT_TEST_WORKFLOW_ID"]
FAIL_POINT = os.environ["AT_TEST_FAIL_POINT"]
PHASE = os.environ["AT_TEST_PHASE"]


@DBOS.step(name="model_crash_decision")
def model_decision() -> dict:
    result = create_deterministic_agent().run_sync("Check item-01 and choose mutation")
    decision = result.output.model_dump()
    with psycopg.connect(FIXTURE_URL) as conn:
        conn.execute(
            """INSERT INTO model_probe (workflow_id, model_call_count)
               VALUES (%s, 1)
               ON CONFLICT (workflow_id) DO UPDATE
               SET model_call_count = model_probe.model_call_count + 1""",
            (WORKFLOW_ID,),
        )
        conn.commit()
    if PHASE == "crash" and FAIL_POINT == "before_model_persist":
        os._exit(78)
    return decision


@DBOS.workflow(name="model_crash_workflow")
def workflow() -> dict:
    decision = model_decision()
    if PHASE == "crash" and FAIL_POINT == "after_model_persist":
        os._exit(79)
    return decision


def main() -> int:
    print(f"worker_pid={os.getpid()}", flush=True)
    DBOS(config={"name": "all-tomorrow-model-crash-probe", "system_database_url": SYSTEM_URL})
    DBOS.launch()
    with SetWorkflowID(WORKFLOW_ID):
        result = workflow()
    print(f"stock_confirmed={result['stock_confirmed']}", flush=True)
    DBOS.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
