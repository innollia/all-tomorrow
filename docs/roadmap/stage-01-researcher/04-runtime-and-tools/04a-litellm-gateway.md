# 04A — LiteLLM + PydanticAI Model Wiring

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0

## 목적

PydanticAI provider/model 계층을 LiteLLM Proxy에 연결하고 00B에서 확정한 retry/usage/privacy contract를 구현한다.

## Path

Researcher
→ AgentExecutionPort/PydanticAI
→ OpenAI-compatible model/provider
→ LiteLLM Proxy
→ provider/model

## 구현

- exact LiteLLM/PydanticAI version
- proxy config example
- env/secret injection
- logical ModelRoute → gateway alias
- usage/cost/model/latency provenance
- retry owner policy 적용
- timeout/error normalization
- OTel propagation

All Tomorrow core에 provider SDK branch를 추가하지 않는다.

## Retry

00B retry table을 그대로 구현한다.

- primary owner 외 retry disabled/bounded
- total retry budget이 layer 중첩으로 곱해지지 않는 test
- rate limit/model timeout/provider unavailable을 서로 구분
- exhausted 결과를 Run evidence로 남김

## Privacy/secret

- provider key는 Proxy runtime이 소유
- Work/Event/prompt artifact에 key/header 금지
- raw prompt/response logging production default off
- canary scan으로 실제 설정 검증

## Requirements

| ID | 요구 | 검증 |
|---|---|---|
| 04A-01 | PydanticAI→LiteLLM 실제 호출 | integration |
| 04A-02 | provider branch 없음 | architecture |
| 04A-03 | retry count가 policy ceiling 초과 안 함 | failure fixture |
| 04A-04 | usage unknown을 0으로 위조하지 않음 | response fixture |
| 04A-05 | secret/raw prompt gateway/telemetry leak 없음 | canary |
| 04A-06 | custom client가 필요하면 실제 gap evidence+ADR 존재 | review gate |

## 완료조건

PydanticAI가 Proxy를 통해 실제 모델을 호출하고 retry/usage/privacy가 00B/00D contract와 일치해야 한다.
