# 00A-3 — Restate Spike

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 00A-1

## 목적

PydanticAI + Restate 조합을 DBOS와 동일한 harness로 검증하고, Restate integration 특유의 wrapping 비용까지 측정한다.

## 연결 원칙

- Restate는 durable mechanism/state journal만 소유
- Goal/Work/Run 의미는 All Tomorrow가 소유
- Restate keyed state를 application canonical domain store로 사용하지 않음
- backend-specific context/type이 domain package로 새지 않게 함

## Integration-shape Check

Restate Python SDK의 PydanticAI integration은 기존 agent를 감싸는 RestateAgent 계열 surface를 제공하므로 DBOS와 같은 모양이라고 가정하지 않는다.

다음을 별도로 측정한다.

- agent wrapper LOC
- model wrapper LOC
- tool/toolset wrapper LOC
- Restate context가 application code에 침투하는 범위
- durable wait/signal을 PydanticAI agent flow와 연결하는 방식
- persisted handler/service/object names의 upgrade compatibility
- ordinary dependency update 때 old in-flight execution recovery

## Restate-specific Checks

공통 D01~D12 외에 기록:

- single-binary runtime 운영 절차
- journal/state 저장 위치와 백업 단위
- signals/promises와 user wait 매핑
- timers/long wait
- keyed state를 쓰지 않고도 필요한 execution semantics를 닫을 수 있는지
- flow-control/queue equivalent가 All Tomorrow priority 요구와 어떻게 맞는지
- 별도 state system이 추가되는 운영 비용
- runtime BSL license가 현재 personal/internal deployment와 향후 public service에 미치는 경계

## Durable Data Footprint

DBOS와 같은 canary를 사용한다.

다음에서 검색:

- application DB
- Restate journal/state
- stdout/stderr
- OTel export
- 추가 gateway 로그

retention, cleanup, backup, encryption-at-rest, large payload 대신 artifact_ref를 쓰는 전략을 기록한다.

## 탈락 조건

DBOS와 동일한 hard gate를 적용한다. Restate라서 acceptance를 낮추지 않는다.

추가로 wrapper/context가 All Tomorrow core에 광범위하게 새어 backend 교체 비용이 커지면 실패로 기록한다.

## 산출물

- exact version
- setup steps
- wrapper/adapter/glue LOC
- D01~D12 결과
- data-footprint 결과
- 운영/라이선스 제약
- Restate를 제거할 때 유지되는 All Tomorrow contract
