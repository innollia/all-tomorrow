# 04D — AWS Single-Node Runtime: deployment contract & runbooks

Region: `ap-northeast-2`. Topology per ADR 0006 D-LOCK-13 (single node: app +
application PostgreSQL + LiteLLM Proxy). This document + `deploy/` are the
IaC/service config; the actual live apply/reboot/restore is an operator action
(it incurs ongoing cost and is gated on explicit approval).

`mutable latest` is forbidden — every image is pinned by digest
(`tests/test_aws_runtime.py` enforces it against `deploy/docker-compose.yaml`).

## Deployment contract (per service)

| Service | Version | Supervisor / autostart | Bind / port | Network policy | Health / readiness | Persistent volume | Secret source | Log dest / retention | Restart | Deploy | Rollback |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all-tomorrow-app | `ghcr.io/innollia/all-tomorrow:0.1.0@sha256:…` | systemd `all-tomorrow.service` → docker compose | `0.0.0.0:8080` (public via TLS ingress) | inbound 443→8080 only; egress to proxy loopback + AWS APIs | `GET /healthz` | none (state in PostgreSQL) | runtime env / SSM | CloudWatch Logs, 30d | `unless-stopped` | bump digest, `compose up -d` | set prior digest, `compose up -d` |
| postgres | `postgres:16.4@sha256:…` | same compose | `127.0.0.1:5432` (private) | local SG only; no public ingress | `pg_isready` | `at_pgdata` volume + EBS | `pg_password` file (0600) | CloudWatch Logs, 30d | `unless-stopped` | snapshot then digest bump | restore snapshot, prior digest |
| litellm-proxy | `ghcr.io/berriai/litellm:main-v1.101.0@sha256:…` | same compose | `127.0.0.1:4000` (private) | loopback only from app | `GET /health/liveliness` | none | runtime env: `AT_GATEWAY_MASTER_KEY`, `AT_OPENAI_API_KEY` | CloudWatch Logs, 30d (no prompt/message logging, D-LOCK-09) | `unless-stopped` | digest bump, `compose up -d` | prior digest, `compose up -d` |

DBOS durable state is a **separate database** (`all_tomorrow_dbos`) on the same
PostgreSQL server — domain and durable state have distinct owners (D-LOCK-10).

## Network / security

- Public surface: HTTPS 443 only, terminating TLS at an ALB / Caddy in front of app:8080.
- PostgreSQL (5432), durable system DB, and the proxy admin port (4000) bind to
  loopback / a private security group — never publicly reachable.
- TLS certificate renewal owner: ACM (ALB) or Caddy auto-renew; recorded here so
  the owner is explicit.
- No protected approval / deployment credential lives on the AWS node
  (D-LOCK-14, 04D-04). Laptop approval secrets stay on the laptop.
- IAM least-privilege inventory:
  - EC2 instance role: `s3:GetObject/PutObject` on the artifact/backup bucket
    (prefix-scoped), `logs:PutLogEvents` to its log group, `ssm:GetParameter` on
    `/all-tomorrow/*`. NO `iam:*`, NO account-wide `s3:*`, NO `ec2:*`.
  - Backups: S3 bucket with SSE, versioning, and a lifecycle rule matching the
    retention below.

## Persistence / backup (separate owners — NOT a single consistent snapshot)

| State | Owner | Mechanism | Schedule | Retention | Restore | Restore verify |
|---|---|---|---|---|---|---|
| application DB (`all_tomorrow`) | app | `pg_dump` → S3 (SSE) or EBS snapshot | hourly | 7d rolling + 1 daily/30d | `pg_restore` into target | `tests/test_aws_runtime.py::restore fixture` (schema + row spot-check) |
| durable system DB (`all_tomorrow_dbos`) | DBOS | `pg_dump` (SDK-safe; no raw table surgery) → S3 | hourly | 7d completed / active kept | `pg_restore` | in-flight Run resumes after restore |
| proxy state | — | none (stateless; config re-provisioned) | — | — | re-deploy config | liveliness probe |

**Application and durable state are NOT one transaction-consistent backup.** After
a restore, run cross-store reconciliation (`DurableRunBridge.reconcile_starting_runs`)
so STARTING Runs with no ExecutionRef converge to one logical external execution
and semantic Run identity is recovered (04D-05).

## Failure scenarios → expected behavior

| Scenario | Expected | Req |
|---|---|---|
| app process restart | systemd/docker restart; DBOS resumes in-flight Runs | 04D-01 |
| whole instance reboot | systemd autostart → compose up → DBOS recovery | 04D-01 |
| LiteLLM unavailable | model step fails UNAVAILABLE; Goal/Work not lost; retried by DBOS step owner | 04D-02 |
| durable runtime restart | DBOS recovers from system DB | 04D-01 |
| PostgreSQL restart | app reconnects (pool); Runs intact | 04D-01 |
| disk/volume remount | data on `at_pgdata`/EBS; no loss | 04D-05 |
| laptop offline | Work stays in durable WAIT; no forged progress | 04D-03 |
| deploy V1→V2 + in-flight Run | replay if compatible, else drain V1 (D-LOCK-03) | 04D-07 |
| backup restore to test env | domain restored + reconciliation recovers identity | 04D-05 |

## Deploy runbook

1. Build + push the app image; capture its `sha256` digest.
2. Update the three `@sha256:…` digests in `deploy/docker-compose.yaml`; commit.
3. On the node: `git pull`, then `sudo systemctl restart all-tomorrow`.
4. Wait for all three healthchecks green: `docker compose ps`.
5. Smoke: `curl -fsS https://<host>/healthz`.

## Rollback runbook

1. Set the three digests back to the previous release's values (recorded per
   deploy) in `deploy/docker-compose.yaml`.
2. If the DB schema changed incompatibly, restore the pre-deploy snapshot first.
3. `sudo systemctl restart all-tomorrow`; confirm healthchecks.
4. Run reconciliation if any Run was in flight during the failed deploy.

## Live apply — operator decision (NOT auto-applied)

Standing up an always-on `ap-northeast-2` node bills continuously and is a
one-way-door spend decision. The IaC/config/runbooks above are complete and
reviewable; the actual provisioning (create instance, attach EBS, ALB+ACM, first
`compose up`) and the L3 reboot/restore/upgrade verifications require the
operator to apply them on the live account.
