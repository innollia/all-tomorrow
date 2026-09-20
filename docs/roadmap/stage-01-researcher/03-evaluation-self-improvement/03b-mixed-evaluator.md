# 03B — Mixed Evaluator

## Status

- 상태: **선행작업 대기**
- 선행조건: 03A 완료
- 지금 시작 가능: **아니오**

## 목적

공통 metric + pre-frozen dynamic criteria + user evidence를 결합하되 평균 점수 하나로 hard regression을 상쇄하지 않는다.

## Evidence

### Common

optional observed values:

- success_rate
- failure_count
- cost
- token_usage
- latency
- retries
- rollbacks
- user_interventions

missing은 UNKNOWN.

### Dynamic

03A에서 candidate 실행 전에 freeze된 criteria만 사용.

각 item:

- id/name/description
- direction
- required/optional
- baseline evidence collection method
- candidate evidence collection method
- acceptance rule/tolerance
- weight는 presentation 보조값일 수 있으나 hard rule을 덮지 않음

### User

- explicit feedback refs
- correction/revert refs
- continued-use outcome
- longer-term outcome refs

## Decision policy

decision:
ACCEPT / REJECT / NEED_MORE_EVIDENCE

### Immediate REJECT

- hard invariant 실패
- protected/security boundary violation
- required regression threshold 초과
- baseline/candidate case set 불일치
- candidate가 frozen criteria/evaluator/fixture를 변경하거나 오염
- required artifact/evidence integrity 실패

### ACCEPT 가능 조건

모두 만족:

1. required criteria 모두 pass
2. hard regression 없음
3. evidence integrity 정상
4. predeclared improvement signal 최소 하나가 실제 관측
5. user evidence가 명확히 반대하면 conflict를 해소할 충분한 근거가 있거나 ACCEPT 대신 NEED_MORE_EVIDENCE
6. required metric이 UNKNOWN이면 해당 criterion이 optional임이 사전 명시되어 있음

### NEED_MORE_EVIDENCE

- evidence conflict
- sample 부족
- required observation unavailable
- difference가 tolerance 안에서 불명확

LLM evaluator가 reason을 만들 수 있어도 이 hard policy를 override하지 못한다.

## Preference hypothesis

사용자 선호 추론은 confidence/evidence/contradiction을 가진 별도 hypothesis이며 explicit command를 override할 authority가 없다.

## Requirements

| ID | 요구 | 검증 |
|---|---|---|
| 03B-01 | hard regression이 평균 개선으로 상쇄되지 않음 | negative fixture |
| 03B-02 | frozen criteria만 사용 | candidate tamper fixture |
| 03B-03 | missing metric=UNKNOWN | unit |
| 03B-04 | user conflict 보존 | mixed evidence fixture |
| 03B-05 | required signal 없이 automatic ACCEPT 불가 | negative |
| 03B-06 | preference hypothesis가 command override 안 함 | acceptance fixture |

## 완료조건

promotion decision이 pre-frozen criteria와 실제 evidence로 설명 가능하고 candidate가 평가 규칙을 자기에게 유리하게 변경할 수 없어야 한다.
