# 04D — AWS Single-Node Runtime

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 완료 + 01 durable bridge + 04A model wiring

## 목적

AWS를 항상 켜진 researcher 중앙 runtime으로 사용한다.

처음부터 distributed control cluster를 만들지 않는다.

## 초기 process

Stage 0 선택 후 최소 topology를 쓴다.

1. All Tomorrow application PostgreSQL
2. All Tomorrow service
3. selected durable backend가 요구하는 runtime/state service
4. LiteLLM Proxy model gateway
5. selected tool gateway — LiteLLM MCP를 선택했다면 4와 같은 process/service일 수 있음

OTel collector/exporter는 실제 backend 요구가 있을 때 추가한다.

## State 경계

논리적으로 다음을 분리한다.

- All Tomorrow application/domain state
- selected durable backend system/journal state
- gateway operational state, if any

durable backend 내부 schema를 All Tomorrow canonical domain으로 직접 조회/수정하지 않는다.

## Crash behavior

service/host restart 뒤 selected durable backend가 in-flight execution을 복구하고, All Tomorrow는 ExecutionRef와 deterministic run identity로 상태를 다시 연결한다.

custom claim/lease/requeue recovery loop를 작성하지 않는다.

## Single-node 이유

초기 personal AWS에서는 가장 작은 production topology부터 닫는다.

multi-host/high-availability가 실제 요구가 될 때만 Stage 0 selection record의 migration trigger를 사용해 다음을 재검토한다.

- 현재 선택 backend의 HA/control-plane 요구
- 라이선스 변화
- 별도 managed/control service 필요성
- 다른 durable backend로 migration할 비용

후보 이름을 이 문서에서 미리 고정하지 않는다.

## Failure-domain Check

model gateway와 tool gateway를 같은 LiteLLM process에 둘 경우 한 process 장애가 두 surface를 동시에 끊는다.

Stage 0에서 이 blast radius가 durable recovery로 충분히 흡수되는지 확인한 결과를 그대로 따른다.

필요하면 tool gateway만 별도 process로 분리한다.

## Laptop

repo mutation과 protected approval은 laptop 경계를 유지한다.

laptop offline은 durable execution을 잃게 하지 않고 기다림/재시도 가능한 상태로 남아야 한다.

## 완료조건

1. AWS reboot 뒤 in-flight researcher work 복구
2. application state와 backend system state 분리
3. model/tool gateway 장애가 Goal 유실로 이어지지 않음
4. laptop offline이 central state 유실로 이어지지 않음
5. custom queue recovery daemon 없음
6. Stage 0에서 고른 최소 process topology와 일치
