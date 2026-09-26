# Data Retention and Privacy Inventory (Stage 00D)

이 문서는 All Tomorrow 00C/00D 아키텍처의 recovery payload, process logs, durable state, telemetry spans, 그리고 artifact store의 보존/격리 정책(Retention & Privacy Inventory)을 공식 정의한다.

## 1. Data Classification (5 Canaries)

시스템을 통과하는 모든 데이터는 다음 5가지 범주로 분류된다:

| 범주 | 설명 | 허용 Surface | 엄격 금지 Surface |
|---|---|---|---|
| `EPHEMERAL_CREDENTIAL` | API 키, 비밀 토큰, 마스터 키 (`sk-*`, `bearer *`) | 인메모리 프로세스 런타임 (마스킹) | Process logs, LiteLLM logs, OTel Spans, App DB, DBOS Journal, Artifact store |
| `GOAL_SEMANTIC_PROMPT` | 사용자 고수준 목표/작업 요약 (`Goal.title`, `Work.title`) | App DB (`at_goals`, `at_works`), 인메모리 | Process logs, LiteLLM spend logs, OTel Spans (raw prompt 금지), DBOS journal |
| `TOOL_INTERMEDIATE_PAYLOAD`| 도구 실행 인자 및 임시 반환값 | 일시적 실행 런타임 | App DB (`at_*`), OTel span attributes (raw payload 금지), Process logs |
| `PAYLOAD_RAW_IMMUTABLE` | 대용량 산출물 바이너리/JSON, 아티팩트 본문 | Artifact Store | App DB (only `ArtifactRef` 허용), OTel Spans, DBOS journal, Process logs |
| `CORRELATION_TOKEN` | 추적 식별자 (`goal_id`, `work_id`, `run_id`, `trace_id`, `execution_id`) | 모든 6개 Surface (공통 추적 키) | (금지 없음 - 단일 추적 트리의 필수 상관 키) |

---

## 2. Storage & Telemetry Surfaces (6 Surfaces)

시스템 내 데이터가 저장되거나 노출될 수 있는 6대 표면과 보존/정제 규칙:

### Surface 1: Process Logs (stdout / stderr)
- **보존 정책**: 단기 진단용 (로컬/호스트 ephemeral).
- **정제(Scrubbing) 규칙**: `EPHEMERAL_CREDENTIAL` 및 `PAYLOAD_RAW_IMMUTABLE` 노출 엄격 금지.
- **위반 시 판정**: 즉시 FAIL (민감정보 누출).

### Surface 2: LiteLLM Proxy / Spend Logs
- **보존 정책**: 토큰 카운트 및 비용 계측 메타데이터.
- **정제(Scrubbing) 규칙**:
  - `store_prompts_in_spend_logs = False`
  - `turn_off_message_logging = True`
  - `EPHEMERAL_CREDENTIAL`, `TOOL_INTERMEDIATE_PAYLOAD`, `PAYLOAD_RAW_IMMUTABLE` 노출 0건.

### Surface 3: OpenTelemetry Telemetry Spans
- **보존 정책**: 분산 추적 백엔드 (Collector / Memory / File).
- **정제(Scrubbing) 규칙**:
  - `capture_content = False` (기본값: raw prompt / tool payload 차단).
  - `sanitize_attributes`: secret 패턴 자동 redaction (`[REDACTED_SECRET]`).
  - `CORRELATION_TOKEN`만 속성으로 허용 (`all_tomorrow.*`).

### Surface 4: PostgreSQL Application DB (`public.at_*`)
- **소유자**: All Tomorrow Application (`at_goals`, `at_works`, `at_runs`, `at_questions`, `at_events`).
- **보존 정책**: 영구 도메인 상태 및 감사 사실 (Audit fact).
- **정제(Scrubbing) 규칙**:
  - `at_works.evidence`에는 `CompletionEvidence` 및 `ArtifactRef`만 저장 (raw payload 금지).
  - `at_runs.execution_ref`에는 external durable execution 링크만 저장.
  - `at_events`는 중요한 상태 전이만 기록 (span 단위 세부 이벤트 폭증 금지).

### Surface 5: Durable Backend Journal (`dbos.*`)
- **소유자**: DBOS Durable Substrate (시스템 테이블, application이 직접 DDL 소유하지 않음).
- **보존 정책**: 워크플로 재생(Replay) 및 크래시 복구(Drain)용 상태 저널.
- **정제(Scrubbing) 규칙**:
  - 비밀 자격증명(`EPHEMERAL_CREDENTIAL`) 및 대용량 아티팩트(`PAYLOAD_RAW_IMMUTABLE`) 영구 저장 금지.
  - V1 워크플로 저널은 V2 런타임에서도 재개/배출(drain) 가능해야 함.

### Surface 6: Artifact Store (`LocalArtifactStore` / Blob Store)
- **소유자**: All Tomorrow Content-Addressed Storage.
- **보존 정책**: 불변 아티팩트 페이로드 (`content_hash` 기반 무결성 검증).
- **정제(Scrubbing) 규칙**:
  - 오직 `PAYLOAD_RAW_IMMUTABLE`만 저장.
  - 비밀 자격증명, raw 프롬프트, 도구 중간값 파일 내 혼입 금지.

---

## 3. Retention Lifecycle and TTL

1. **Active Runs**: 런타임 중 활성 상태 유지, 비정상 중단 시 타임아웃(Supervisor timeout)에 의해 FAILED 전이 및 자원 해제.
2. **Crash Replay Context**: 이전 프로세스 실패 후 복구 시까지 보존, 복구 완료 후 메모리 해제.
3. **Artifact Payloads**: 영구 CAS 보존, 상위 Work의 증거(CompletionEvidence)에서 참조.
4. **Domain Events**: 장기 감사 사실로 영구 보존.
