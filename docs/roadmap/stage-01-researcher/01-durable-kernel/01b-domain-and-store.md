# 01B — Goal/Work Domain and Store

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01A

## 목적

Goal/Work를 외부 workflow engine과 독립된 All Tomorrow domain으로 구현한다.

## Domain

GoalRecord와 WorkRecord는 사용자·프로젝트 의미만 표현한다.

WorkRecord에는 외부 실행을 연결하기 위한 ExecutionRef를 둘 수 있다.

ExecutionRef:
- backend
- execution_id
- version optional

ExecutionRef는 DBOS handle/status 객체가 아니다.

## Store 책임

WorkStateStore:
- create/get/update goal
- create/get/list/update work
- attach_execution_ref
- semantic transition + provenance event

optimistic revision과 state transition/event atomicity는 application DB에서 유지한다.

## 하지 말 것

이 store에 다음 method를 추가하지 않는다.

- claim_next_work
- heartbeat_work
- requeue_expired_work
- lease owner 검사
- backend retry counter

그것은 DurableExecutionPort 구현이 사용하는 substrate 책임이다.

## Priority

All Tomorrow Priority P0~P6는 semantic policy다.

adapter가 backend enqueue priority로 매핑한다. backend numeric range나 queue representation을 domain enum에 노출하지 않는다.

## 완료조건

1. Goal/Work를 durable backend 없이 저장/조회 가능
2. DBOS를 import하지 않는 domain/store test 존재
3. ExecutionRef만으로 외부 실행과 연결 가능
4. semantic transition과 provenance event가 atomic
