import os
os.environ["AT_TEST_POSTGRES_URL"] = "postgresql:///at_dbos_probe"
from dbos import DBOS, SetWorkflowID
DBOS(config={"name": "test-app", "system_database_url": os.environ["AT_TEST_POSTGRES_URL"]})
DBOS.launch()
@DBOS.workflow(name="generic_workflow")
def generic_workflow(payload):
    return payload

with SetWorkflowID("gwf-test-1"):
    handle = DBOS.start_workflow(generic_workflow, {"test": 123})
status = DBOS.get_workflow_status("gwf-test-1")
print("status:", status.status)
DBOS.destroy()
