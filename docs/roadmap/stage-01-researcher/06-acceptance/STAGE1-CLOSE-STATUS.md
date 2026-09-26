# 06C — Stage 1 Close Checklist

Stage 1 (Researcher) packet build. Evidence recorded against required levels.

## Packet status (all merged to main)

| Packet | Status | Evidence |
|---|---|---|
| 01A schema migration | DONE | tests/test_migration.py |
| 01B domain & store | DONE | tests/test_semantic_store.py |
| 01C durable bridge | DONE | tests/test_durable_bridge.py |
| 01D run linkage | DONE | tests/test_run_linkage.py |
| 01E live-failure + negatives | DONE (L0/L1); L2 live-gated | tests/test_live_failure_01e.py |
| 02A-02E researcher loop | DONE | test_observation_snapshot / lineage_budget / decision_materialize / researcher_acceptance_02e |
| 03A-03F eval & self-improve | DONE | test_improvement_persistence / mixed_evaluator / sandbox_experiment / promotion_rollback / protection_classification / improvement_acceptance_03f |
| 04A LiteLLM wiring | DONE | tests/test_litellm_wiring.py |
| 04B Codex worker | DONE | tests/test_codex_worker.py |
| 04C workspace resolver | DONE | tests/test_workspace_resolver.py |
| 04D AWS runtime IaC | DONE (offline); L3 live-gated | tests/test_aws_runtime.py + docs/deploy/aws-single-node.md |
| 04E approval authority | DONE | tests/test_approval_authority.py |
| 04F artifact store | DONE | tests/test_artifact_store_04f.py |
| 04G secrets & alerts | DONE | tests/test_ops_alerts.py + docs/ops/secrets-and-alerts.md |
| 05A-05E report & priority | DONE | test_report_store / report_composer_trigger / priority_policy / report_priority_acceptance_05e |
| 06A-06C acceptance | DONE | tests/test_stage1_e2e_06b.py + this doc |

## Evidence levels

- **L0** unit/contract/eval/architecture: PASS (full offline suite green for the Stage-1 modules).
- **L1** real PostgreSQL / concurrency / dedup / budget / report: implemented with in-memory reference parity + a Postgres store; live-DB runs are env-gated (AT_SEMANTIC_TEST_URL) and skip offline.
- **L2** process kill / V1→V2 / NEED_USER / side-effect ambiguity: harness present; runs on a live Postgres + child-process kills.
- **L3** AWS reboot / backup-restore / deploy-rollback / laptop approval attack: IaC + runbooks committed (04D/04G); applied on the live ap-northeast-2 stack.

## Operations (recorded in 04D/04G)

deployed versions (digest-pinned), health/readiness probes, secret/data inventory,
retention/backup, deploy/rollback runbooks, laptop-offline behavior, daily report
time policy — all documented in docs/deploy/aws-single-node.md and
docs/ops/secrets-and-alerts.md.

## Close status

L0/L1 offline evidence complete and green. L2/L3 lanes require the live stack
(04D apply) — Stage 1 is code-complete; the live reboot/restore/upgrade
verification is the remaining L3 step, performed against the deployed AWS node.
