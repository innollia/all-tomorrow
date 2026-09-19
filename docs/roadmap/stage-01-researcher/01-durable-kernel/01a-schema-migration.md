# 01A — Semantic Schema Migration

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 완료
- 완료 후 열림: 01B

## 목적

기존 thin tasks를 All Tomorrow가 실제로 소유하는 Goal/Work semantic state로 확장한다.

durable backend의 queue/lease/checkpoint schema는 복제하지 않는다.

## 수정 방향

새 migration은 0001/0002를 과거 migration으로 유지하고 추가한다.

### goals

유지할 의미:
- goal_id
- user_id
- project_id
- title
- objective
- semantic status
- priority
- origin
- metadata
- revision
- timestamps

### work_items

tasks를 rename해 기존 row를 보존한다.

유지할 의미:
- work_id
- goal_id
- user_id
- project_id
- title
- semantic status
- priority
- origin
- trace_id
- payload/reference
- wait_reason
- parent_work_id
- revision
- timestamps

외부 실행 연결:
- execution_backend nullable
- execution_id nullable
- execution_version nullable

이 세 필드는 provenance/linkage이며 external engine의 state machine을 복제하지 않는다.

## 삭제된 기존 계획

다음 column을 All Tomorrow queue authority 목적으로 추가하지 않는다.

- claimed_by
- lease_expires_at
- attempt_count

다음 index도 만들지 않는다.

- custom claim partial index
- lease recovery index

priority는 사용자/프로젝트 의미를 보존하는 domain field다. 실제 enqueue 시 durable backend priority로 변환한다.

## runs / events

기존 오류는 별도로 바로잡는다.

- runs.trace_id UNIQUE 제거
- 한 Work 아래 여러 execution/run attempt 허용
- event provenance가 run 정리와 함께 cascade 삭제되지 않게 수정
- external execution ref와 trace linkage 가능하게 함

## 하지 말 것

- DBOS system table을 migration에서 생성/수정
- DBOS workflow status를 work status enum으로 그대로 복제
- future Hatchet/Temporal 내부 id를 위한 vendor별 column 추가
- 0001을 과거 migration 대신 다시 쓰기

## 완료조건

1. 기존 task data가 보존됨
2. Goal/Work semantic state 저장 가능
3. Work가 external execution ref를 vendor-neutral하게 참조 가능
4. queue/lease mechanics가 schema에 들어오지 않음
5. multi-run/multi-trace provenance 요구를 만족
