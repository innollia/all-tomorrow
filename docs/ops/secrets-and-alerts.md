# 04G — Secrets, Operational Alerts & Dependency Security

Lowers operations-security-contract.md into a concrete plan for the ap-northeast-2
single-node deployment (04D). No raw secret appears here, in any Event, artifact,
config example, or log.

## Secret inventory

AWS ordinary-runtime secret backend: **AWS SSM Parameter Store (SecureString)**
under `/all-tomorrow/*`, read by the EC2 instance role (least privilege). The
Laptop Approval Authority secret domain is entirely separate and never on AWS.

| secret_id | consumer | read permission | rotation / revocation | reload behavior | last-rotated metadata | audit |
|---|---|---|---|---|---|---|
| `/all-tomorrow/gateway_master_key` | LiteLLM proxy | instance role (SSM GetParameter, prefix-scoped) | rotate via SSM put + `compose restart litellm-proxy`; revoke = overwrite + restart | restart proxy | SSM param `LastModifiedDate` | CloudTrail on the param |
| `/all-tomorrow/openai_api_key` | LiteLLM proxy | instance role | provider console rotate → SSM put → restart | restart proxy | SSM `LastModifiedDate` | CloudTrail |
| `/all-tomorrow/pg_password` | app + postgres | instance role | rotate password → SSM put → `compose restart` | restart app+db | SSM `LastModifiedDate` | CloudTrail |
| laptop approval write token | Laptop Approval Authority ONLY | laptop keychain (NOT on AWS) | rotate on laptop; revoke invalidates issued approvals | authority restart | keychain metadata | authority audit_trail() |

Rules: only `secret_id`/ref is stored in the domain; a credential-looking value is
never persisted to an Event/artifact/log; the approval/protected-deployment secret
does NOT exist on AWS (04D-04, S1-04G-01).

## Rotation / revocation runbook (S1-04G-02)

1. Put the new value: `aws ssm put-parameter --name /all-tomorrow/<id> --type SecureString --overwrite --value <new>` (value never logged).
2. Restart the consumer: `sudo systemctl restart all-tomorrow` (or the single service).
3. Confirm health probes green.
4. Revocation = overwrite with a fresh value + restart; issued laptop approvals are
   invalidated by rotating the authority write token on the laptop.

## Alert catalog (S1-04G-03/04)

Encoded in `src/all_tomorrow/ops/alerts.py` (evaluator unit-tested). Each rule
carries metric, threshold/window, severity, destination, runbook ref:

- reconciliation_stuck, delivery_repair_required, run_replan_storm, budget_exhausted,
  backup_stale (S1-04G-04), durable_unavailable, gateway_unavailable, auth_attack,
  report_trigger_missed, storage_pressure.

At least one path (`backup_stale`, `reconciliation_stuck`) is verified by
`tests/test_ops_alerts.py`; the L3 wiring to CloudWatch alarms is applied with the
04D stack.

## Dependency security plan (S1-04G-05)

Planned CI lanes (not created in this planning packet):
- vulnerability scan (pip-audit) on the lockfile
- SBOM artifact (CycloneDX) per release
- license inventory + policy gate
- lockfile integrity / image digest pin (already enforced for deploy images)
- update-PR provenance recorded on the release
- high-risk install/build scripts reviewed in a disposable sandbox (Stage 3 discovery rail)

Security updates still pass the durable replay/compatibility gate — no bypass
(S1-04G-06).
