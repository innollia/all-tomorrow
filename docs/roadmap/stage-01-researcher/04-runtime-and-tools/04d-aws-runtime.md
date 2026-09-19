# 04D — AWS Single-Node Runtime

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01 durable bridge + 04A model wiring

## 목적

AWS를 항상 켜진 researcher 중앙 runtime으로 사용한다.

처음부터 distributed control cluster를 만들지 않는다.

## 초기 process

AWS host 최소:
1. PostgreSQL
2. All Tomorrow service + DBOS runtime
3. LiteLLM Proxy

필요하면 OTel exporter/collector를 추가할 수 있지만 Stage 1 필수 heavy backend는 아니다.

## DB 경계

한 PostgreSQL server에 둘 수 있으나 논리적으로:
- All Tomorrow application/domain state
- DBOS system state

를 분리한다.

DBOS 내부 schema를 All Tomorrow canonical domain으로 조회하거나 수정하지 않는다.

## Crash behavior

service/host restart 뒤 DBOS가 in-flight workflow를 복구하고, All Tomorrow는 ExecutionRef를 통해 상태를 다시 연결한다.

custom lease scan/requeue loop를 작성하지 않는다.

## Single-node 이유

초기 AWS 무료/소규모 runtime에서는 DBOS library만으로 먼저 닫는다.

multi-host/high-availability 요구가 생기면 별도 spike:
- DBOS Conductor의 현재 라이선스/운영 조건 검토
- 또는 Hatchet/Temporal durable backend migration

을 수행한다.

## Laptop

repo mutation과 protected approval은 laptop 경계를 유지한다.

laptop offline은 durable execution을 잃게 하지 않고 기다림/재시도 가능한 상태로 남아야 한다.

## 완료조건

1. AWS reboot 뒤 in-flight researcher work 복구
2. DB/domain state와 DBOS system state 분리
3. LiteLLM 장애가 Goal 유실로 이어지지 않음
4. laptop offline이 central state 유실로 이어지지 않음
5. custom queue recovery daemon 없음
