# ADR 0006: Stage 0 Architecture Lock

Status: Accepted

Date: 2026-09-26

## Context

Stage 0(OSS Assembly & Architecture Proof)의 00A~00D가 개발완료/개발중 상태로 main(`2b627a1`)에 병합됐다. 00E는 spike 결과를 추측이 아닌 확정 architecture decision으로 동결하고, Stage 1의 모든 packet이 더 이상 Stage 0 결과를 추측하지 않도록 만드는 rewrite gate다.

이 ADR은 [00E packet](../roadmap/stage-00-assembly/00e-architecture-lock.md)이 "반드시 닫을 결정"으로 지정한 14개 항목을, [00A-5 Selection Record](../roadmap/stage-00-assembly/00a-5-selection.md)와 병합된 실제 코드/테스트 증거에 근거해 확정한다. 근거 없는 "선호한다/쓸 예정이다"는 이 문서에 담지 않는다.

증거 기준선:
- 결정적 결합 흐름: `tests/test_combined_gateway_agent.py::...[durable_crash]` 통과, `.artifacts/00a/selection-flow.xml`
- 재시도 책임 모델: `src/all_tomorrow/harness/retry_matrix.py`
- 아키텍처 fitness 강제: `tests/test_architecture_fitness.py`
- 보존/프라이버시: `docs/architecture/retention-inventory.md` + `tests/test_retention_inventory.py`
- CI rail: `.github/workflows/ci.yml` (7 lanes)

## Decision

### D-LOCK-01 — Selected durable backend + exact version
- **선택**: DBOS 3.0.0.
- **consumption mode**: package (Python worker + application PostgreSQL). 별도 durable 서버/저널 저장소를 추가하지 않는다.
- **증거**: 00A-5 결합 흐름 통과, `pyproject.toml`의 `dbos==3.0.0`.
- **rejected alternative**: Restate 1.7.10. 신뢰성/설치 실패가 아니라, 현재 Python 3.13·단일 노드·PostgreSQL 목표에서 별도 서버 + 2종 상태 시스템 운영 비용이 결정 요인. Temporal/Hatchet/Prefect는 migration candidate로만 유지.
- **owned/non-owned**: All Tomorrow는 Goal/Work/Run 의미·권한·provenance·외부 effect를 소유; DBOS는 실행/step journal·wait/timer/recovery를 소유.

### D-LOCK-02 — run_id → external identity mapping
- external execution ID = `work_id:run_id`.
- 같은 Run 재시도 = 동일 ID. 새 의미적 시도 = 새 Run(새 ID).
- ExecutionRef(execution_backend/execution_id/execution_version)는 **Run이 소유**하며 Work에 두지 않는다. `tests/test_architecture_fitness.py`가 Work의 단일 ExecutionRef 소유를 금지로 강제.

### D-LOCK-03 — Upgrade strategy (replay vs blue/green/drain)
- 호환 가능한 app/dependency 변경 = 같은 compatibility version으로 **replay**.
- 단계 순서/이름·입출력의 비호환 변경 = 새 버전으로 분리하고 기존 worker를 유지해 **drain**. test expectation을 새 버전에 맞춰 덮지 않는다; migration/drain plan이 먼저다.
- **증거**: `tests/test_upgrade_rail.py`(V1 history → candidate replay/drain, step 중복 방지), PydanticAI 2.45.0→2.46.0 및 V2 finalization 복구 확인.

### D-LOCK-04 — Model retry primary owner
- 유일한 자동 retry owner = **DBOS model step**(transient predicate, 최대 6 attempts, 2초 간격).
- OpenAI SDK `max_retries=0`, LiteLLM `num_retries=0`/fallback 없음, PydanticAI validation retry 1(출력 검증 교정만).
- All Tomorrow 자동 semantic retry = 0(정책상 재시도는 새 Run으로 명시).
- **증거**: `retry_matrix.py`의 실제 클라이언트 설정값.

### D-LOCK-05 — Tool transport retry primary owner
- MCP tool retry = 0(PydanticAI). transport 재시도를 별도로 두지 않는다. tool 실패는 step 실패로 표면화하고 DBOS step 경계에서 처리한다.

### D-LOCK-06 — priority/delay/signal/cancel mapping
- priority는 semantic domain field이며 adapter가 backend priority로 변환한다(도메인이 backend 큐 우선순위를 복제하지 않음).
- wait/signal payload와 모델 결정은 typed 값으로 adapter 경계에서 변환. DBOS 내부 type/schema를 domain에 노출하지 않는다.
- cancel/timer는 DBOS wait/timer 위에 mapping; 구체 attempt/timeout/backoff 수치는 Stage 1 01A~01C에서 실제 store와 함께 확정.

### D-LOCK-07 — LiteLLM MCP Gateway 채택 여부
- **채택**. LiteLLM Proxy 1.101.0 하나가 model gateway + fixed MCP gateway를 겸한다. 두 route가 같은 프로세스 장애 영역을 공유하는 비용은 수용.

### D-LOCK-08 — FastMCP fallback 필요 여부
- **불필요**. 실제 PydanticAI 연결·namespace·discovery·access filter·privacy 설정에 구조적 장애가 없었다. LiteLLM MCP 계약이 깨지거나 model/tool 장애 영역 분리가 실제 요구가 될 때만 재평가.

### D-LOCK-09 — LiteLLM persistence/logging on/off + retention
- callbacks off, `store_prompts_in_spend_logs=False`, `turn_off_message_logging=True`, prompt/spend/message 원문 수집 off, runtime env credential 사용, gateway DB/virtual keys 미도입.
- **증거**: `retention-inventory.md` Surface 2.

### D-LOCK-10 — durable journal data classification/retention/backup
- Journal = trusted sensitive store. 최소 typed 입력 + artifact 참조만 전달; provider key/불필요 원문 금지. DBOS system DB와 domain DB는 별도 database/schema·권한 경계.
- 완료 journal 보존 목표 7일; active/waiting 실행은 만료 삭제 금지. 임의 SQL로 backend 내부 표 삭제 금지(SDK API 사용).
- 백업: PostgreSQL domain/system DB 모두. 외부 effect는 DB 복원으로 되돌아가지 않으므로 복원 시 재조정.
- **증거**: `retention-inventory.md` Surface 4/5, 00A-5 데이터/운영 책임.

### D-LOCK-11 — artifact storage/ref strategy
- content-addressed storage(`content_hash`). App DB에는 `ArtifactRef`만 저장(raw payload 금지). `PAYLOAD_RAW_IMMUTABLE`만 artifact store에 저장.
- **증거**: `retention-inventory.md` Surface 6, `src/all_tomorrow/domain/artifacts.py`.

### D-LOCK-12 — existing PipelineRuntime disposition
- **compatibility-only**. 고유 가치가 있는 deterministic recipe 기능은 보존하되, 외부 substrate와 중복되는 durability/retry/queue 기능은 축소한다. 즉시 삭제하지 않고, Stage 1에서 researcher path 핵심인지 compatibility layer인지 packet별로 확정.

### D-LOCK-13 — AWS 최소 process topology
- 단일 노드: Python worker(DBOS embedded) + application PostgreSQL + 별도 환경의 LiteLLM Proxy(dependency graph 격리).
- container image는 아직 채택하지 않음; 향후 배포 시 digest pin(mutable latest 금지, fitness test가 강제).
- 실제 AWS 배포·암호화·복구 SLA는 이 spike가 인증하지 않음 → Stage 1 04D(AWS runtime)의 L3 evidence로 확정.

### D-LOCK-14 — protected approval credential boundary
- protected credential은 AWS runtime env/config에 두지 않는다(fitness test가 강제). 승인 대기→signal→완료 경로를 결합 흐름에서 확인. 구체 threat model은 Stage 1 04E(approval authority)에서 확정.

## Consequences

- Stage 1의 placeholder(selected backend/version, run_id mapping, retry owner, upgrade strategy, gateway 선택, PipelineRuntime disposition, retention, credential boundary)가 concrete value로 채워져, 01A를 추측 없이 시작할 수 있다.
- DBOS/LiteLLM upstream version·API·라이선스 변화를 계속 추적해야 한다(ADR 0005 Dependency Boundary).
- 단일 프로세스 장애 영역(model+tool gateway 공유)과 단일 노드 가정은 multi-host 요구가 생기면 D-ESCAPE-01에 따라 재검토한다.

## Escape / Migration triggers (D-ESCAPE-01)

durable 선택을 재검토하는 조건:
- 다중 호스트 운영이 현재 DBOS 구성보다 복잡해지거나, Restate 고유 keyed service/배포 모델이 실제로 필요해질 때.
- gateway의 필수 MCP 계약이 깨지거나 model/tool 장애 영역 분리가 실제 요구가 될 때 → FastMCP 또는 분리 프로세스 평가.
- 일반 upstream 업데이트나 미실행 장애 조합만으로는 재평가를 열지 않는다.

## Guardrails

- 이 lock을 이유로 custom durable queue/lease/heartbeat/recovery daemon/model client를 추가하지 않는다.
- backend 내부 status/schema를 canonical domain으로 복제하지 않는다.
- substrate version 변경은 old-history replay/contract CI 없이 merge하지 않는다.
