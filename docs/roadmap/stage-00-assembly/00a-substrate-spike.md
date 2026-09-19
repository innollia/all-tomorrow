# 00A — Substrate Spike & Selection

## Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 없음

## 목적

문서 비교가 아니라 작은 실행 spike로 OSS 조합을 고른다.

## 반드시 검증할 조합

Primary:
- PydanticAI
- DBOS
- LiteLLM-compatible endpoint
- PostgreSQL

Comparison:
- Temporal의 PydanticAI native durable integration
- Hatchet의 embedded/self-host 경계와 custom integration 비용

비교 후보는 설치 자체가 목적이 아니다. Primary 조합에서 막힌 요구가 실제로 있을 때 교체 비용을 확인한다.

## Spike

별도 production module을 만들지 않고 tests/spikes 또는 experiments 아래 최소 코드를 둔다.

검증:
- PydanticAI agent가 LiteLLM-compatible base URL을 통해 model 호출
- PydanticAI tool 또는 MCP tool 한 번 호출
- 같은 agent 실행을 DBOS durable workflow 안에서 수행
- stable-id DynamicToolset 또는 MCP gateway를 통해 새 tool schema를 새 run에서 발견
- in-flight run은 recovery 때 당시 기록된 tool definition을 일관되게 재사용
- per-run executing MCPToolset 추가가 제한되는 조건을 재현하고 우회가 framework fork 없이 가능한지 확인
- process kill 뒤 recovery
- 동일 workflow ID 중복 시작 시 side effect 중복 방지
- queue priority와 delay
- durable send/recv 또는 event로 HITL 대기/재개
- OpenTelemetry trace 생성
- DBOS system state와 All Tomorrow application state 분리

실제 유료 provider 호출이 없어도 local/mock OpenAI-compatible endpoint로 contract를 검증할 수 있다.

## 판단 기준

Primary를 채택하려면:
- All Tomorrow core에 DBOS/PydanticAI 내부 타입이 퍼지지 않음
- custom claim/lease/heartbeat가 필요하지 않음
- user wait/restart가 backend primitive 위에서 구현 가능
- external execution ID를 provenance로 연결 가능
- 기존 worker CLI를 tool/adapter로 호출 가능
- tool registry가 늘어나도 agent/workflow 코드를 tool마다 재배포하지 않아도 됨
- PydanticAI/DBOS의 persisted agent/toolset/step name 안정성 요구를 지킬 수 있음
- backend 교체 seam을 설명할 수 있음

## 즉시 탈락 조건

- Goal/Work domain을 DBOS workflow schema에 맞춰 왜곡해야 함
- raw provider credential을 workflow payload에 넣어야 함
- crash recovery가 side effect를 안전하게 다룰 수 없음
- PydanticAI durable integration 때문에 All Tomorrow의 동적 tool registry를 framework fork 없이 표현할 수 없음
- agent/toolset ID나 persisted step name 변경이 일반적인 tool 추가만으로 in-flight workflow를 자주 strand시킴

## 완료조건

실행 가능한 spike와 결과 기록이 있고, Primary 채택/기각 이유와 fallback 조건이 명시되어 있다.
