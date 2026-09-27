# Stage 0 Close — Live Verification (2026-09-27)

Stage 0를 닫기 위해 남아 있던 live evidence(L2/L3)를 실제 환경에서 수집한 기록이다.

## 1. WSL live lab 전체 스위트 (L2)

- 환경: WSL Ubuntu 24.04, PostgreSQL 16, Restate Server 1.7.10, LiteLLM Proxy 1.101.0, FastMCP 4.0.5, restate-sdk 1.0.5, Python 3.13
- 재현: `scripts/lab/root_setup.sh`(root) → `scripts/lab/user_setup.sh` → `scripts/lab/pin_setup.sh` → `scripts/lab/run.sh`
- 결과: **591 passed, 0 failed** (`scripts/run_00a_live.sh`, dbos 3.1.0)
- lab에서 skip된 5건은 전부 별도 실행으로 통과:
  - `test_dbos_backend_outage.py` — root + `AT_TEST_ALLOW_POSTGRES_STOP=1` (PostgreSQL 실제 stop/start): 1 passed
  - `test_restate_backend_outage.py` — lab 밖 단독 + `AT_TEST_ALLOW_RESTATE_STOP=1`: 1 passed
  - `test_workers.py` Antigravity/OpenCode CLI smoke — Windows 호스트(Antigravity CLI 1.2.12 설치): passed
  - `test_live_common_lifecycle.py` 신규 upgrade drain — Restate candidate에는 해당 없음(DBOS 전용), DBOS candidate passed

## 2. Live lab에서 발견해 고친 것

| 테스트 | 원인 | 조치 |
|---|---|---|
| `test_combined_gateway_agent[agent]` | fixture model은 `echo_canary`가 있으면 그것을 우선 호출하는데 단언은 `identify`만 기대 | alpha 경로 tool이 gateway를 왕복해 결정에 반영됐는지로 단언 교정 |
| `test_cancel_survives_restart_and_later_signal[restate]` | Restate는 cancel을 durable하게 기록하지만 handler에 전달해야 적용되므로 worker가 죽어 있으면 invocation이 suspended로 남음 | cancel 후 worker 재기동(“survives restart” 시나리오 그대로), 실패 시 ingress 응답을 단언 메시지에 포함 |

## 3. D-UP-01 — dependency update history compatibility

- 변경: `dbos==3.0.0` → `dbos==3.1.0` (`pyproject.toml`, `uv.lock`)
- `opentelemetry-sdk 1.45.0`은 `pydantic-ai==2.46.0`과 해석 불가로 기각(업그레이드 PR 후보에서 제외)
- 증거: `test_durable_backend_dependency_upgrade_drains_v1_history[dbos]` — dbos 3.0.0으로 시작해 signal 대기 중인 workflow를 kill, dbos 3.1.0 프로세스가 같은 history를 이어받아 완료. span에 두 버전이 모두 기록되고 model 호출은 1회(중복 effect 없음).
- 같은 PR에서 C-series crash/restart, E-01~E-08 eval, secret/canary negative, MCP list/call, model gateway contract 전부 lab에서 통과.

## 4. E-RUNTIME-01 — AWS backup/restore/restart (L3)

- 대상: ap-northeast-2 `i-034a2f4ca37b9e293` (t3.small, compose: `all-tomorrow-app` + `postgres`, systemd `all-tomorrow`)
- 절차(SSM `AWS-RunShellScript`):
  1. `pg_dump -Fc`로 백업 파일 생성 (`/opt/all-tomorrow/backups/`)
  2. restore canary row 삽입 후 재백업
  3. 별도 DB `restore_check`에 `pg_restore` → 테이블 수 원본과 일치, canary row 복원 확인 → `restore_check` 삭제
  4. `systemctl restart all-tomorrow` → `/healthz` **200**, canary row 재시작 후 유지
- 참고: 현재 live app DB는 canary 테이블 1개뿐이다(배포 app이 아직 semantic schema migration을 live DB에 적용하지 않음). 백업/복원 절차 자체는 검증됐고, schema가 늘어나도 같은 `pg_dump -Fc`/`pg_restore` 경로를 쓴다.
- reboot 생존은 04D 배포 시 확인(`docs/deploy/aws-single-node.md`).
