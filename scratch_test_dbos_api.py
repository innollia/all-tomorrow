import os
os.environ["AT_TEST_POSTGRES_URL"] = "postgresql:///at_dbos_probe"
from dbos import DBOS, SetWorkflowID

DBOS(config={"name": "test-app", "system_database_url": os.environ["AT_TEST_POSTGRES_URL"]})
DBOS.launch()
print("get_workflow_status:", DBOS.get_workflow_status("non-existent"))
print("send to non-existent:")
try:
    DBOS.send("non-existent", {"a": 1}, topic="t")
    print("send OK")
except Exception as e:
    print("send Error:", type(e), e)

@DBOS.workflow(name="dummy_wf")
def dummy(x):
    return x * 2

with SetWorkflowID("test-dummy-1"):
    handle = DBOS.start_workflow(dummy, 21)
print("handle type:", type(handle))
print("retrieved:", DBOS.retrieve_workflow("test-dummy-1"))
print("status:", DBOS.get_workflow_status("test-dummy-1"))
print("result:", DBOS.get_result("test-dummy-1"))
DBOS.destroy()
