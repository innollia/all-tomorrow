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

## 콘솔 기능과 tailnet 기기 로그인 (2026-10-19, 배포 전)

`feat/port-console-features`의 콘솔(사용량·프로젝트 패널·아이디어 공장)과 로그인 변경을 이 노드에 올릴 때 필요한 것. 아직 배포하지 않았다(작업한 PC에 AWS 자격 증명이 없어 SSM 접근 불가).

- **tailnet 기기 자동 로그인**: 노드 호스트에서 `tailscale serve --bg --https=443 http://127.0.0.1:8081`로 tailnet 이름(`https://all-tomorrow-central.<tailnet>.ts.net`)에 HTTPS를 연다. serve는 연결한 tailnet 사용자를 `Tailscale-User-Login` 헤더로 붙인다. 앱은 이 헤더를 **8081 포트로 들어온 요청에서만** 믿고, 로그인이 `ALL_TOMORROW_TAILNET_LOGINS`에 있으면 비밀번호 없이 세션을 준다.
  - 8081은 호스트 loopback에만 공개(`127.0.0.1:8081:8081`)하므로 serve만 닿는다. 8080(공개 Caddy·tailnet 직접·device agent)으로 들어온 헤더는 무시한다.
  - 출발지 주소로 확인(whois)하지 않는 이유: 2026-10-19 측정에서 tailnet 요청이 앱에 `172.18.0.1`(도커 브리지)로 도착해 tailnet 주소가 보이지 않았다.
  - serve 경로는 HTTPS라 `ALL_TOMORROW_COOKIE_SECURE=true` 그대로 동작한다. 평문 `http://100.97.113.3:8080`에서는 Secure 쿠키가 버려져 로그인이 유지되지 않는다(기존부터 그랬음). tailnet에서는 serve 주소를 쓴다.
  - tailnet 관리 화면에서 MagicDNS와 HTTPS 인증서가 켜져 있어야 serve HTTPS가 동작한다.
  - 노드 env: `ALL_TOMORROW_TAILNET_LOGINS=<소유자 Tailscale 로그인>`, `ALL_TOMORROW_TAILSCALE_SERVE_PORT=8081`.
- **세션 30일**: `ALL_TOMORROW_SESSION_TTL_DAYS`(기본 30).
- **비밀번호 변경 유지**: 계정 화면에서 바꾼 비밀번호(PBKDF2 해시)와 "모든 기기 로그아웃" 세대값을 `ALL_TOMORROW_AUTH_STATE`(기본 `<콘솔 데이터>/auth-state.json`, 600)에 저장한다. 이후에는 env의 `ALL_TOMORROW_ADMIN_PASSWORD`가 아니라 저장된 해시가 쓰인다. 초기화하려면 그 파일을 지운다. `at_console` 볼륨이 이 파일과 콘솔 데이터를 보존한다.

### 배포 기록 (2026-10-20)

- 대상: `all-tomorrow-node` (i-034a2f4ca37b9e293, t3.small). 이 노드가 tailnet의 `all-tomorrow-central`(100.97.113.3)이다.
- 이전 상태: 앱 `all-tomorrow:0.3.0@sha256:fd08b5b0e17d…`(노드 `/opt/all-tomorrow/deploy-prev-image.txt`에 기록), `ALL_TOMORROW_COOKIE_SECURE=true`. 배포 전 DB 백업 `all_tomorrow-20261019T150427Z.dump`를 S3에 업로드했다.
- 방법: 이 브랜치 소스(`046b680`)를 S3 임시 객체로 넘겨 노드에서 `docker build`(작업 PC에 Docker 없음, 노드 x86_64). 이미지 `all-tomorrow:console-046b680`(로컬 태그, ECR 미등록).
- 반영: `/opt/all-tomorrow/docker-compose.override.yaml`(systemd의 `docker compose up -d`가 자동 포함)로 앱만 교체했다. 콘솔 데이터는 `at_console` 볼륨에 두고, 수집기 토큰은 `/opt/all-tomorrow/console.env`(600)에 두었다. postgres·caddy는 그대로다.
- `tailscale serve --bg --https=443 http://127.0.0.1:8081` → `https://all-tomorrow-central.tailc5ef02.ts.net/` (tailnet only).
- 확인:
  - 작업 PC(aaaa, tailnet)에서 serve 주소 `/login`이 303으로 세션 쿠키를 받았고, `/`와 `/api/devices`가 200이었다. 브라우저에서도 비밀번호 없이 콘솔 홈으로 들어가 9개 화면이 오류 없이 렌더링됐다.
  - 직접 `:8080`과 공개 Caddy로 위조 헤더를 보내면 로그인 폼(200)만 나왔다.
  - 공개 `/healthz` 200을 확인했다. 사용량·프로젝트 스냅숏 push는 204였다.
- 롤백: `docker-compose.override.yaml` 삭제 → `docker compose -f docker-compose.yaml -f docker-compose.caddy.yaml up -d --no-deps all-tomorrow-app` → `tailscale serve --https=443 off`.
- 남은 일: 이 이미지를 ECR에 올리고 digest로 고정하는 정식 릴리스 절차(PR 병합 후), 아이디어 공장 실행기(`IDEA_FACTORY_ENABLED`)와 gateway는 노드에서 켜지 않았다(읽기 전용 화면만 동작).
