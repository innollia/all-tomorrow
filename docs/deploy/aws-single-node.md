# 04D — AWS Single-Node Runtime: deployment contract & runbooks

Region: `ap-northeast-2`. Topology per ADR 0006 D-LOCK-13 (single node: app +
application PostgreSQL + LiteLLM Proxy). This document + `deploy/` are the
IaC/service config; the actual live apply/reboot/restore is an operator action
(it incurs ongoing cost and is gated on explicit approval).

`mutable latest` is forbidden — every image is pinned by digest

## Deployed image record (ap-northeast-2, account 761558630442)

Built and pushed 2026-09-27; digests pinned in `deploy/docker-compose.yaml`:

| service | image@digest |
|---|---|
| all-tomorrow-app | `761558630442.dkr.ecr.ap-northeast-2.amazonaws.com/all-tomorrow:0.1.0@sha256:f46cced5cfb3ce6ba436a3e9c7f3672452b6edb110a30d2fd690149f24fca58f` |
| postgres | `postgres:16.4@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412` |
| litellm-proxy | `ghcr.io/berriai/litellm:main-stable@sha256:87f34979b9f8cb274fac90ca8a4fdda07d8480de22755562a26adeb95ce20d02` |

Build/push commands (reproducible):

```
docker build -t all-tomorrow:0.1.0 .
aws ecr get-login-password --region ap-northeast-2 | docker login --username AWS --password-stdin 761558630442.dkr.ecr.ap-northeast-2.amazonaws.com
docker tag all-tomorrow:0.1.0 761558630442.dkr.ecr.ap-northeast-2.amazonaws.com/all-tomorrow:0.1.0
docker push 761558630442.dkr.ecr.ap-northeast-2.amazonaws.com/all-tomorrow:0.1.0
```

Image smoke test before push: container boots, `/healthz` → 200 (auth env required; fail-closed without it).

## Live single-node deployment (ap-northeast-2, 2026-09-27)

Provisioned and serving:

| resource | value |
|---|---|
| instance | `i-034a2f4ca37b9e293` (t3.small, AL2023 `ami-03137ee2d0c5af1fe`, 20GB gp3) |
| public endpoint | `https://15.164.99.125.sslip.io/healthz` → `200` (Caddy 리버스 프록시가 8080 앱으로 전달, Let's Encrypt 자동 인증서) |
| security group | `sg-03fd323bce8b24f5e` — inbound 80 (ACME/redirect) + 443 (https app) + 22 (admin) only; 8080은 확인 후 닫음; postgres bound `127.0.0.1:5432` (private) |
| IAM instance profile | `all-tomorrow-node` — `AmazonEC2ContainerRegistryReadOnly` + `AmazonSSMManagedInstanceCore` (no protected/approval credential on the node, per 04D-04) |
| stack | `docker compose` (postgres@digest + app@ECR digest); secrets (pg password, session secret, admin password) generated on the node, never in the image or repo |
| autostart | systemd `all-tomorrow.service` (enabled) — survives reboot (04D-01) |
| remote admin | AWS SSM (no SSH key distributed) |

Health verified after a full instance reboot (SSM re-registered, stack came back via the systemd unit).

### Lesson: EC2 user-data must not be pre-base64-encoded when passed via `--user-data file://`
The AWS CLI base64-encodes `file://` user-data itself; passing an already-base64 blob double-encodes it and cloud-init silently skips the script (cloud-init "finished in ~8s", no bootstrap log, docker absent). Fix used here: install + configure the stack over SSM `AWS-RunShellScript` on the running node. For a fresh launch, pass the RAW script text to `--user-data file://script.sh`.


Rollback: re-pin the previous `@sha256:` digest for `all-tomorrow-app` in `deploy/docker-compose.yaml` and `docker compose up -d` — image immutability guarantees the prior artifact is byte-identical.

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

## HTTPS ingress (Caddy, 2026-09-29)

도메인을 별도로 구매하지 않고 `15.164.99.125.sslip.io` (공인 IP를 그대로 매핑해주는 무료 도메인)를 써서
Caddy 컨테이너를 80/443 앞단에 세웠다. Caddy가 Let's Encrypt로 인증서를 자동 발급·갱신한다.

- 접속 주소: `https://15.164.99.125.sslip.io`
- 구성 파일: `/opt/all-tomorrow/Caddyfile` (호스트), `/opt/all-tomorrow/docker-compose.caddy.yaml` (compose override)
- 기동 명령(호스트에서): `docker compose -f docker-compose.yaml -f docker-compose.caddy.yaml up -d`
- 앱 쿠키: `ALL_TOMORROW_COOKIE_SECURE=true`로 전환(https 전제이므로 Secure 쿠키 사용)
- 보안그룹: 80/443 오픈, 동작 확인 후 8080(직접 앱 접근)은 닫음. 22(SSM 전용 관리)는 유지.
- 인증서 저장: Caddy 볼륨 `at_caddy_data`/`at_caddy_config`에 유지되어 재기동해도 재발급 없이 사용.

## Postgres 자동 백업 (systemd timer, 2026-09-29)

호스트의 systemd timer가 매일 Postgres를 덤프해 로컬 보관 + S3 업로드를 수행한다.

- 스크립트: `/usr/local/bin/all-tomorrow-pg-backup.sh` (호스트) — `docker exec ... pg_dump` → 로컬 `/opt/all-tomorrow/backups/`에 저장 → `aws s3 cp`로 업로드 → 로컬 7일 초과 파일 삭제
- 타이머: `all-tomorrow-backup.timer` (매일 03:00 UTC, `RandomizedDelaySec=300`) / 서비스: `all-tomorrow-backup.service`
- 대상 버킷: `all-tomorrow-backups-761558630442` (ap-northeast-2), 버저닝 활성화, SSE(AES256) 암호화, 퍼블릭 액세스 전체 차단
- 인스턴스 IAM 역할(`all-tomorrow-node`)에 해당 버킷 한정 `s3:PutObject`/`s3:GetObject`/`s3:ListBucket` 인라인 정책(`AllTomorrowBackupsS3Write`) 추가
- 파일명 형식: `all_tomorrow-<UTC타임스탬프>.dump` (custom format, `pg_dump -F c`)

### 복원 방법

```bash
# 1. S3에서 원하는 덤프를 내려받는다
aws s3 cp s3://all-tomorrow-backups-761558630442/all_tomorrow-<TS>.dump ./restore.dump --region ap-northeast-2

# 2. 임시(또는 실제) Postgres 컨테이너에 복사 후 복원
docker cp ./restore.dump <postgres-container>:/tmp/restore.dump
docker exec <postgres-container> pg_restore -U at_app -d <target-db> /tmp/restore.dump

# 3. 검증: 테이블 수 비교
docker exec <postgres-container> psql -U at_app -d <target-db> -t \
  -c "select count(*) from information_schema.tables where table_schema='public';"
```

`OWNER TO at_app` 관련 경고(대상 DB에 같은 롤이 없는 경우)는 실제 운영 DB로 복원할 때는 발생하지 않으며,
검증용 임시 DB로 복원할 때만 나타나는 부수 경고다(데이터/스키마 자체는 정상 복원됨).

2026-09-29 수동 실행 검증: 덤프 `all_tomorrow-20260929T085454Z.dump` (50065 bytes)를 임시
`postgres:16.4` 컨테이너에 복원 → `public` 스키마 테이블 수 25개, 원본 운영 DB 테이블 수 25개로 일치 확인.
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

## Edge token (eve Discord bridge)

- `ALL_TOMORROW_EDGE_TOKEN` gates `/internal/edge/discord/decide` (bearer). Without it the request gets 401.
- eve-scene-runtime sets the same value in its `ALL_TOMORROW_EDGE_TOKEN`, plus `ALL_TOMORROW_EDGE_URL=http://<node>:8080`.
- On the live node the token is generated and kept on the node only (via SSM). It is never printed locally.
