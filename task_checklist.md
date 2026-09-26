# Phase 1: DBOS Adapter ownership & boundary cleanup
- [x] Remove manual writes/reads to `dbos.workflow_status`, `dbos.notifications`, `dbos.workflow_output`.
- [x] Use `dbos.DBOS` public API (`get_workflow_status()`, `send()`, `retrieve_workflow()`, `get_result()`, `cancel_workflow()`, `start_workflow()`) in `DBOSDurableAdapter`.
- [x] Store only application-owned mapping (`public.at_run_executions`, `public.at_signals_seen`) in PostgreSQL.
- [x] Remove broad exception swallowing (`_init_db()` should fail fast or fail explicitly).

# Phase 2: E2E Durable Wait & Process Recovery
- [x] Connect `WalkingSkeletonOrchestrator` to real DBOS workflow execution with durable wait (`DBOS.recv()`).
- [x] In `test_end_to_end_walking_skeleton`, ensure worker process executes DBOS workflow that actually suspends on `DBOS.recv()`, and is signaled via `DBOSDurableAdapter.signal()` / `DBOS.send()`.
- [x] Verify workflow resumes and completes in separate process boundary across process restart.

# Phase 3: C-04 / C-05 Crash Window Separation with Real Process Kill
- [x] C-04: Delivery STARTING committed to PostgreSQL → kill application process before external side effect starts. Restart new process → reconcile without duplicate external effect.
- [x] C-05: External effect started/committed → kill application process before local external reference attach. Restart new process → recover execution using idempotency key / external request id, attach reference without re-executing effect.

# Phase 4: C-07, C-09, C-10 Real Failure Boundaries
- [x] C-07: Real worker process timeout (kill on timeout), child process cleanup verification, Run/Work terminal failure status, failure evidence preserved, Goal preserved.
- [x] C-09: Two independent OS processes / reconcilers concurrently competing on the same PostgreSQL durable delivery record using CAS/locking → converges to single execution without divergent attach.
- [x] C-10: Real dependency process / service boundary outage injection (e.g. stopping upstream service or simulating network fault), recording UNKNOWN/failed evidence, verify recovery after service restart.

# Phase 5: Complete Data Retention Canary Inventory
- [x] Inject distinct canaries: prompt canary, tool input canary, tool output canary, secret canary, artifact canary.
- [x] Inspect all required surfaces: application PostgreSQL DB, DBOS durable journal/state, LiteLLM Proxy logs/spend logs, OTel spans/export, stdout, stderr, artifact store.
- [x] Assert expected-present vs expected-absent retention criteria.

# Phase 6: Full Verification & Status Update
- [x] Run all tests (C-01 through C-10 + retention + artifact probe + end-to-end walking skeleton).
- [x] Verify regression across existing tests.
- [x] Update `docs/roadmap.md` and `docs/roadmap/stage-00-assembly/index.md` & `00c-failure-walking-skeleton.md` based on actual evidence.
