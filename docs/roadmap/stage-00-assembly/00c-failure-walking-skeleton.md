# 00C — Failure Walking Skeleton

## Status

- 상태: **선행작업 대기**
- 선행조건: 00A + 00B

## 목적

기능을 많이 만들기 전에 가장 위험한 실패 경계를 한 번 끝까지 관통한다.

## 한 개의 skeleton

user request
→ All Tomorrow semantic Work
→ durable execution start
→ PydanticAI agent
→ 한 번의 worker/tool 호출
→ NEED_USER 성격의 durable wait
→ 사용자 signal
→ 계속 실행
→ artifact/result 기록
→ 완료

## 강제 실패

같은 skeleton에서 순서대로 검증:
- model 호출 직전 process kill
- tool side effect 직후 process kill
- user wait 중 process restart
- application Run commit 직후, durable enqueue 직전 process kill
- durable enqueue 직후, ExecutionRef attach 직전 process kill
- 동일 run_id start 요청 두 번
- worker timeout
- app version이 바뀐 상태에서 old workflow recovery

각 실패에서:
- Goal/Work identity가 남음
- side effect가 허용된 semantics 이상으로 중복되지 않음
- 사용자가 같은 질문을 불필요하게 두 번 받지 않음
- provenance가 끊기지 않음
- reconciliation이 같은 run_id로 기존 durable execution을 회수하고 새 side effect를 만들지 않음

## DB 배치

초기에는 하나의 PostgreSQL 서버를 써도 된다.

논리적으로는 분리:
- All Tomorrow application/domain DB
- durable backend system DB/schema

backend 내부 테이블을 application migration에서 관리하지 않는다.

## 완료조건

실제 PostgreSQL에서 process kill/restart를 포함한 skeleton이 통과한다. mock-only 결과로 완료 처리하지 않는다.


## Data-retention probe

같은 skeleton에 식별 가능한 canary 문자열을 prompt/tool input/tool output에 각각 넣는다.

완료 뒤:
- All Tomorrow application DB
- durable backend state/journal
- LiteLLM logs/spend logs
- OTel exporter
- process stdout/stderr

를 확인해 canary가 어느 저장소에 남는지 표로 기록한다.

"안 남아야 하는 곳"에서 발견되면 해당 substrate/config는 acceptance 실패다.

large file/raw document는 durable step output으로 직접 반환하지 않고 artifact store/ref pattern을 시험한다.
