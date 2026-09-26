import os
import sys
import psycopg
from dbos import DBOS, SetWorkflowID

system_url = os.environ.get("AT_TEST_POSTGRES_URL", "postgresql:///at_dbos_probe")

DBOS(config={
    "name": "all-tomorrow-walking-skeleton-worker",
    "system_database_url": system_url,
    "application_version": "ws-v1",
})
DBOS.launch()

@DBOS.step()
def step1():
    print("step1 executing")
    return "done1"

@DBOS.workflow(name="test_step_wf")
def my_wf():
    print("workflow start")
    s = step1()
    print("workflow after step1:", s)
    return s

wfid = "test-step-crash-2"

status = DBOS.get_workflow_status(wfid)
print("status before:", status)

try:
    with SetWorkflowID(wfid):
        res = my_wf()
        print("result:", res)
except Exception as e:
    print("caught error:", type(e), e)
finally:
    DBOS.destroy(destroy_registry=True)
