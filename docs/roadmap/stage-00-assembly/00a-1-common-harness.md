# 00A-1 — Common Harness

## Status

- 상태: **시작안했음**
- 지금 시작 가능: **예**
- 선행조건: 없음

## 목적

DBOS와 Restate에 완전히 같은 입력과 실패를 주기 위한 최소 walking-skeleton harness를 먼저 만든다.

후보별 편의를 위해 acceptance를 바꾸지 않는다.

## 구현 범위

최소 skeleton:

1. deterministic PydanticAI agent 또는 TestModel
2. typed input/output
3. 한 개의 read-only tool
4. 한 개의 idempotency가 필요한 mutation tool stub
5. durable wait/signal 지점
6. timer/delay 지점
7. execution identity
8. OTel correlation ID
9. process kill 지점을 명시적으로 주입할 수 있는 test hook

실제 GitHub/Eve/filesystem mutation은 이 단계에서 붙이지 않는다.

## Canonical Scenarios

각 durable candidate에 동일하게 실행할 scenario ID를 고정한다.

- D01 normal completion
- D02 kill before model result persist
- D03 kill after model result persist
- D04 kill immediately after external side effect
- D05 duplicate start with same execution identity
- D06 user wait → process restart → signal → resume
- D07 long timer/delay → restart → resume
- D08 cancel
- D09 backend temporary unavailable → reconnect
- D10 old in-flight execution under ordinary application/dependency upgrade
- D11 two logical Runs for one Work stay distinct
- D12 OTel correlation survives recovery

## Side-effect Fixture

mutation tool은 외부 시스템 흉내를 내는 별도 fixture store에 다음을 남긴다.

- idempotency key
- call count
- committed value
- reconciliation lookup

D04에서 duplicate mutation이 나면 durable candidate가 통과했다고 보지 않는다. durable retry만 믿지 말고 application-level idempotency/reconciliation seam을 검증한다.

## Result Schema

각 scenario 결과는 같은 구조로 남긴다.

- scenario_id
- candidate
- version
- pass/fail
- manual steps
- custom glue LOC
- adapter LOC
- processes required
- persistent state systems
- recovery notes
- persisted payload notes
- trace notes

## Retry Matrix

다음 층별 retry default를 조사하고 실제 설정을 기록한다.

- provider SDK
- LiteLLM model gateway
- PydanticAI
- durable backend
- All Tomorrow semantic Work retry

같은 failure에 두 층 이상이 독립 retry하지 않도록 테스트 설정을 명시한다.

## 완료조건

- 공통 harness가 특정 durable backend import 없이 존재
- D01~D12를 같은 방식으로 실행할 수 있음
- candidate adapter 외 코드는 DBOS/Restate 이름을 몰라도 됨
- scenario result를 기계적으로 비교 가능
