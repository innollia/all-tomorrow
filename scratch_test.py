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

@DBOS.workflow(name="test_wf")
def my_wf(arg):
    return f"hello-{arg}"

wfid = "test-crash-1"

# Check status in dbos
status = DBOS.get_workflow_status(wfid)
print("status before:", status)

try:
    with SetWorkflowID(wfid):
        res = my_wf("world")
        print("result:", res)
except Exception as e:
    print("caught error:", type(e), e)
finally:
    DBOS.destroy(destroy_registry=True)
