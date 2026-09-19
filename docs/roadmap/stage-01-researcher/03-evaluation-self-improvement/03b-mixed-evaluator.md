# 03B — Mixed Evaluator

## Status

- 상태: **선행작업 대기**
- 선행조건: 03A 완료
- 지금 시작 가능: **아니오**

## 목적

고정 benchmark 한 개만으로 자기개선을 승인하지 않고, 공통 metric + 동적 기준 + 사용자 evidence를 함께 평가한다.

## 수정 파일

- 수정: `src/all_tomorrow/evaluation.py`
- 새 파일: `src/all_tomorrow/evaluation_policy.py`
- 수정: `tests/test_evaluation.py`
- 새 테스트: `tests/test_evaluation_policy.py`

## EvaluationEvidence

세 묶음:

### common

- success_rate
- failure_count
- cost
- token_usage
- latency
- retries
- rollbacks
- user_interventions

모든 값은 optional. 없는 값을 0으로 추정하지 않는다.

### dynamic

criteria item:

- name
- description
- direction: higher/lower/boolean/custom
- baseline value/evidence ref
- candidate value/evidence ref
- weight optional

criteria 자체가 proposal/context에서 생성될 수 있고 version/ref를 가진다.

### user

- explicit feedback refs
- continued-use evidence
- revert/correction evidence
- longer-term outcome refs

## Decision semantics

user feedback도 absolute veto/ground truth가 아니다.

evaluator는:

- clear regression
- clear improvement
- evidence conflict
- insufficient evidence

를 구분.

decision enum:

- ACCEPT
- REJECT
- NEED_MORE_EVIDENCE

평균 점수 하나로 모든 종류를 합쳐 false precision을 만들지 않는다.

## Preference hypothesis

사용자 선호 추론은 별도 evidence-backed hypothesis로 남길 수 있지만:

- confidence
- evidence refs
- contradiction refs

를 가져야 함.

이 hypothesis는 user 명시적 command를 silently substitute하는 권한이 아님.

## 테스트

- metric improvement + user negative → conflict/추가 evidence 가능
- clear failure regression → reject
- user positive 하나만으로 자동 accept 안 됨
- missing metrics는 unknown
- dynamic criterion version/ref 보존
- preference hypothesis가 command override로 변환되지 않음

## 완료조건

서로 다른 신호를 잃지 않은 채 promotion decision을 만들고 conflict를 명시적으로 보존.
