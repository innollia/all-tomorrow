# 00D — Observability / Eval / CI Seam

## Status

- 상태: **선행작업 대기**
- 선행조건: 00C

## 목적

처음부터 관측·평가 가능한 seam을 만들되 무거운 운영 제품을 추가하지 않는다.

## Observability

OpenTelemetry를 공통 contract로 사용한다.

필수 correlation:
- goal_id
- work_id
- All Tomorrow trace_id
- external execution id
- agent/model span
- worker/tool execution ref

OpenTelemetry SDK/TracerProvider는 프로세스당 하나만 구성한다. PydanticAI, durable backend, FastMCP가 그 context를 공유하게 하고 자체 tracing framework를 중복 구현하지 않는다.

### Telemetry ownership

- PydanticAI: agent/model/tool semantic spans
- selected durable backend: workflow/invocation recovery spans
- FastMCP: MCP transport/delegation spans
- All Tomorrow Event: domain/audit fact

Event log를 trace backend처럼 모든 span으로 복제하지 않는다. Event에는 Goal/Work 상태 변화, user question, authority decision, artifact/proposal 같은 장기 domain fact만 남긴다.

FastMCP span이 다른 MCP-aware instrumentation과 중복되면 `FASTMCP_TELEMETRY_MODE=propagation_only`를 우선 검증한다.

### Privacy defaults

PydanticAI instrumentation은 production 기본값으로:
- `include_content=False`
- `include_binary_content=False`
- `include_model_request_parameters=False`

를 spike한다. 필요한 debugging content는 별도 명시적 opt-in 경로로만 허용한다.

OTel attribute에는 raw prompt, tool args/result, secret, credential, 개인 원문을 기본 저장하지 않는다.

Stage 0에서는 Langfuse/대형 telemetry backend self-host를 요구하지 않는다. console/in-memory/가벼운 OTLP collector로 contract만 검증 가능하다.

## Evaluation

첫 eval engine은 Pydantic Evals를 사용한다.

최소 regression dataset:
- structured decision validity
- tool selection
- NEED_USER 판단
- secret redaction
- duplicate-work prevention 결과
- source ownership 위반 방지

Promptfoo는 adversarial/red-team 요구가 생겼을 때 추가 후보이며 Stage 0 dependency가 아니다.

## CI

GitHub Actions에서:
- unit
- integration
- eval regression
- architecture fitness checks

를 실행할 수 있는 seam을 만든다.

protected self-change 승인 권한은 GitHub review로 대체하지 않는다. laptop Approval Authority가 계속 최종 보안 경계다.

## 완료조건

한 skeleton 실행을 trace로 따라갈 수 있고, 같은 실행을 작은 eval dataset으로 회귀 검증하며, CI에서 자동 실행 가능하다.

추가로:
- 같은 MCP call이 중복 span tree로 보이지 않음
- Event row 수가 trace span 수에 비례해 폭증하지 않음
- telemetry export에서 prompt/secret fixture가 검색되지 않음


## Dependency / Upgrade Rail

OSS를 많이 붙이는 만큼 버전 변화 자체를 Stage 0 failure mode로 취급한다.

초기 원칙:
- production substrate(PydanticAI, durable backend SDK, FastMCP, LiteLLM)는 exact/lockfile pin
- Docker image는 mutable `latest` 금지
- GitHub Actions도 version/digest 관리
- Dependabot으로 Python/GitHub Actions/Docker update PR 생성
- 새 버전은 직접 main에 자동 반영하지 않고 compatibility CI를 통과한 PR만 merge
- security patch도 in-flight durable replay test를 생략하지 않음

Dependabot의 기본 update PR + cooldown을 이용하고, substrate 관련 업데이트는 별도 group으로 묶지 말지 실제 CI 비용을 보고 정한다.

### Upgrade CI

dependency PR에서 추가로:
- persisted operation/toolset name snapshot
- old fixture history/replay compatibility
- MCP list/call contract
- model gateway contract
- crash/restart integration
- eval regression

을 실행한다.

dependency update가 durable history를 깨면 "테스트 수정 후 merge"가 아니라 migration/drain 계획이 먼저다.
