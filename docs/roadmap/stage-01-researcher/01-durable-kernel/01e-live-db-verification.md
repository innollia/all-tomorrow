# 01E — Live Failure Verification

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01A~01D

## 목적

mock SQL이 아니라 실제 PostgreSQL과 실제 durable backend로 경계를 증명한다.

## 환경

초기 single-node에서는 한 PostgreSQL server를 사용할 수 있다.

분리:
- application/domain database 또는 schema
- DBOS system database/schema

backend 내부 migration을 All Tomorrow migration test가 소유하지 않는다.

## 필수 시나리오

1. semantic migration chain
2. Goal/Work 저장 후 application restart
3. Run commit 후 enqueue 직전 crash → reconciliation
4. enqueue 후 ExecutionRef attach 직전 crash → reconciliation
5. 같은 run_id start 두 번 → 하나의 durable execution
6. queue priority/delay
7. model/tool step 사이 process kill
8. NEED_USER wait 중 restart → answer signal → 계속 실행
9. external mutation 직후 crash에서 idempotency/reconciliation
10. Work → 여러 Run → 여러 external execution lineage
11. event/audit retention
12. OTel trace correlation
13. application version 변경 중 old in-flight execution recovery/drain

## Versioning

DBOS를 채택하면 application version이 recovery에 영향을 주므로 blue/green 또는 old-version drain 전략을 실제로 시험한다.

이 검증 없이 self-modification promotion을 Stage 1에서 허용하지 않는다.

## Backend Escape Test

test double 또는 최소 alternate adapter를 사용해 DurableExecutionPort가 DBOS type에 묶이지 않았음을 검증한다.

Hatchet/Temporal을 production으로 설치할 필요는 없다.

## 완료조건

위 failure scenario가 실제 DB에서 통과하고 전체 regression suite도 통과한다.
