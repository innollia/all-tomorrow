# 00B-1 — Domain Identity & State Lock

## Status
- 상태: **시작안했음**
- 지금 시작 가능: **예**
- 선행조건: 00A
- 완료 후 열림: 00B-2, 00B-3

## 목적
Goal/Work/Run/ExecutionRef/Outcome/Event/Question/Source/Project identity와 state transition을 코드로 옮길 수 있는 수준으로 잠근다.

## 구현 예정 위치
- 새/수정: src/all_tomorrow/domain/ids.py
- 새/수정: src/all_tomorrow/domain/state.py
- 새: src/all_tomorrow/domain/outcomes.py
- 새: src/all_tomorrow/domain/events.py
- 새: src/all_tomorrow/domain/sources.py
- 테스트: tests/domain/test_identity_state_contract.py

실제 repo 구조가 다르면 00E에서 경로를 조정하되 타입 책임은 합치지 않는다.

## 확정 타입
- GoalId, WorkId, RunId, ExecutionRef
- GoalStatus / WorkStatus / RunStatus
- OutcomeRecord / CompletionEvidence
- EventRecord
- CanonicalError
- SourceRef / ProjectRecord

## 핵심 결정
- Work 1:N historical Run
- 기본 active Run per Work = 1
- ExecutionRef는 Run 소유
- Run success ≠ Work success
- Work/Goal SUCCEEDED에는 CompletionEvidence 필요
- Goal terminal transition은 completion policy가 판정
- terminal object 재사용 금지

## DB 영향
01A migration 계획이 이 identity를 따라야 한다.
Work table에 execution_backend/execution_id 금지.
Run table이 external execution linkage를 가진다.

## Requirements
- S0-00B1-01: Goal/Work/Run transition table 완성
- S0-00B1-02: active Run invariant 결정
- S0-00B1-03: CompletionEvidence 없는 Work/Goal success 금지
- S0-00B1-04: Event/Error/SourceRef canonical schema 확정
- S0-00B1-05: 01A~01D 문서와 identity 충돌 0

## 완료 증거
- state transition table
- proposed type signatures
- schema diff review
- negative fixtures: terminal revive, two active Runs, Work-level ExecutionRef
