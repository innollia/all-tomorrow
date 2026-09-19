# Stage 1.3 — Evaluation and Self-Improvement

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 02-researcher-loop 완료
- 다음으로 여는 작업: ordinary auto-promotion, protected approval path

## Goal

Researcher가 자기 개선 후보를 만들고 실제 evidence로 비교한 뒤, 허용된 변경은 자동 적용하고 실패 시 되돌릴 수 있게 한다.

## Read with

- ../../decisions/0004-self-modification-and-approval-boundary.md
- 02-researcher-loop.md

## Generic Lifecycle

observation
→ research / hypothesis
→ improvement proposal
→ sandbox experiment
→ evaluation
→ promotion / rejection
→ monitoring
→ rollback if needed

reflection_prompt_optimizer, api_problem_fixer 같은 전용 self-improvement taxonomy는 만들지 않는다.

## Evaluation Signals

### Common metrics

- success rate
- cost/token usage
- latency
- retry/rollback
- user intervention

### Dynamic criteria

Goal/Work의 실제 성공 조건에 따라 metacognition이 평가 기준을 만들고 수정할 수 있다.

### User evidence

- 명시적 평가
- 반복 사용 여부
- 되돌림
- 수정 요구
- 장기 outcome

사용자의 즉시 평가는 중요한 evidence지만 절대 ground truth가 아니다.

추론된 심층 선호는 가설이며, 명시적 선택을 몰래 다른 선택으로 바꾸지 않는다.

## Ordinary Self-Change

평가 후 자동 promotion + 사후 보고 가능:

- prompt/agent config
- model/resource selection policy
- metacognitive policy
- evaluation logic
- pipeline/adapter/worker
- internal algorithm/refactor
- 일반 application code

## Protected Change

자동 promotion 불가:

- budget/concurrency/rate ceiling 확대
- production write 권한 확대
- secret/credential 접근 확대
- approval 약화/우회
- kill switch/rollback/audit 약화
- protected 영역 축소

sandbox/evaluation은 가능하지만 production은 laptop Approval Authority 승인 필요.

## Done When

1. ordinary improvement가 sandbox 비교 후 auto-promotion
2. regression 발견 시 rollback
3. protected change가 AWS 단독으로 production 적용되지 않음
4. user feedback과 metric 충돌을 evidence conflict로 보존
5. 평가 기준 자체도 이후 improvement 대상으로 관찰 가능
