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

PydanticAI의 OpenTelemetry instrumentation을 우선 사용하고, 자체 tracing framework를 중복 구현하지 않는다.

Stage 0에서는 Langfuse/대형 telemetry backend self-host를 요구하지 않는다. stdout/file/가벼운 collector exporter로 contract만 검증 가능하다.

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
