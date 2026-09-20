# Failure, Retry & Recovery Contract

00B 이후 durable execution, gateway, worker, trigger가 공유하는 실패 의미를 정의한다.

## 1. Retry ownership

같은 실패를 여러 계층이 독립적으로 retry하지 않는다.

00B 완료 전에 각 failure class마다 정확히 하나의 primary retry owner와 다음을 확정한다.

- retryable error set
- max attempts 또는 budget
- timeout
- backoff/jitter policy
- idempotency requirement
- exhausted 결과
- telemetry fields

provider SDK / LiteLLM / PydanticAI / durable backend의 기본 retry가 겹치면 명시적으로 disable/bound한다. owner를 결정하지 않은 상태로 00B를 완료하지 않는다.

## 2. External mutation semantics

외부 mutation fixture는 최소 두 값을 분리한다.

- invocation_count: adapter/tool이 실제 호출된 횟수
- applied_effect_count: 외부 시스템에 commit된 효과 횟수

"호출 1회"와 "효과 1회"를 혼동하지 않는다.

mutation class마다 허용 semantics를 선언한다.

- IDEMPOTENT_REPLAY: 같은 key 재호출 가능, applied effect는 1회
- RECONCILE_BEFORE_RETRY: 결과 불명 시 조회/reconciliation 후 재호출 결정
- NON_RETRYABLE_AMBIGUOUS: 자동 재호출 금지, NEED_USER/repair Work

durable engine의 replay만으로 exactly-once external effect를 가정하지 않는다.

## 3. Cross-store start protocol

Application DB와 durable backend 사이에 distributed transaction을 만들지 않는다.

1. Run(STARTING)을 application DB에 commit
2. run_id를 deterministic external identity/idempotency key로 start
3. external handle 획득
4. ExecutionRef를 같은 Run에 attach
5. attach 완료 후 RUNNING 등 semantic state로 전환

### Reconciliation

STARTING + no ExecutionRef Run을 대상으로:

1. row revision 또는 DB lock으로 한 reconciler가 해당 Run을 소유
2. 같은 run_id로 external get/start
3. existing execution이면 그 handle 회수
4. absent이면 idempotent start
5. ExecutionRef attach를 compare-and-set
6. 이미 다른 reconciler가 attach했으면 동일 ref인지 검증 후 종료
7. ref 충돌 또는 둘 이상의 logical execution이 관측되면 invariant violation으로 fail closed

reconciliation은 bounded retry policy를 가진다. 영구 실패는 숨기지 않고 explicit repair/FAILED state와 Event를 남긴다.

## 4. Real crash injection

process crash requirement는 별도 child/service process와 test-controlled barrier를 사용한다.

예:
- BEFORE_MODEL_CALL
- AFTER_EXTERNAL_EFFECT_COMMIT_BEFORE_LOCAL_RECORD
- AFTER_RUN_COMMIT_BEFORE_EXTERNAL_START
- AFTER_EXTERNAL_START_BEFORE_REF_ATTACH
- WHILE_WAITING_USER

barrier 도달을 parent test가 관측한 뒤 process를 실제 종료한다. 동일 프로세스의 exception은 L2 crash 증거가 아니다.

## 5. Version upgrade compatibility

persisted history와 연결되는 이름/serialization/schema/version은 compatibility data다.

upgrade test는 최소:

1. V1에서 in-flight execution 생성
2. durable state 유지
3. V1 process 종료
4. V2 배포 또는 side-by-side start
5. V2가 history를 안전하게 replay/resume하는지 검증
6. 불가능하면 V1 drain 경로로 복구됨을 검증
7. migration/drain이 완료되기 전에 incompatible V1 runtime을 제거하지 않음

Stage 0 Architecture Lock에서 실제 strategy를 direct-replay, blue-green-drain, 또는 명시된 다른 방식 중 하나로 확정한다.

## 6. Trigger/time failure semantics

schedule/trigger는 timezone-aware instant와 logical period identity를 분리한다.

- duplicate fire는 idempotency key로 한 Work만 생성
- missed run은 explicit misfire policy에 따름
- clock/DST 변화가 logical period 중복을 만들지 않음
- update/cancel은 revision 이후 old fire를 무효화
- condition watcher는 last observation/cursor를 durable하게 저장

## 7. Unknown state

측정하지 못한 상태를 성공/0/empty로 바꾸지 않는다.

외부 side effect의 commit 여부, 비용, tool result, execution 존재 여부가 불명확하면 UNKNOWN/AMBIGUOUS로 보존하고 reconciliation 또는 사용자 개입으로 넘긴다.
