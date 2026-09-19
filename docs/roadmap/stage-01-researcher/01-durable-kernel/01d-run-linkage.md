# 01D — Run / Compatibility Linkage

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01B + 01C

## 목적

기존 Run/PipelineRuntime 자산을 버리지 않으면서 새 durable/agent substrate와 연결한다.

## 역할 구분

- Work: All Tomorrow semantic unit
- ExecutionRef: durable backend execution
- Agent run: PydanticAI의 한 agent interaction
- Legacy Run/PipelineRuntime: 기존 deterministic/versioned recipe 실행 기록

이 네 개를 하나의 id로 합치지 않는다.

## 기존 PipelineRuntime

즉시 삭제하지 않는다.

Stage 0 결과에 따라:
- deterministic recipe가 유용하면 DurableExecutionPort 안에서 하나의 executor로 유지
- researcher의 agentic decision path는 PydanticAI를 우선
- retry/recovery ownership은 DBOS와 중복시키지 않음

PipelineRuntime 내부 retry가 남는 경우 그 retry는 bounded node-level policy일 뿐 durable process recovery가 아니다.

## Provenance

All Tomorrow trace에서 최소 연결:
- work_id
- execution backend/id/version
- legacy run_id가 있으면 run_id
- PydanticAI/OTel span ref
- worker/tool request id

## NEED_USER

기존 user_questions table은 사용자 UI/answer authorization projection으로 유지할 수 있다.

그러나 durable suspension/recovery는 backend message/event primitive를 사용한다.

질문 projection과 durable signal의 연결은 idempotent해야 한다.

## 완료조건

1. Work 하나가 여러 실행 시도를 참조 가능
2. 기존 PipelineRuntime regression 보존
3. researcher path가 custom PipelineRuntime에 강제 종속되지 않음
4. NEED_USER restart가 backend durable primitive로 통과
5. trace에서 모든 external execution을 연결 가능
