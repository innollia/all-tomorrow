# 03C — Generic Sandbox Experiment

## Status

- 상태: **선행작업 대기**
- 선행조건: 03A + 03B 완료
- 지금 시작 가능: **아니오**
- code/repo candidate 추가 의존성: 04C workspace + coding worker

## 목적

production 변경 전에 baseline/candidate를 동일 frozen case set/criteria로 bounded comparison한다.

## ExperimentSpec

- proposal_id
- target_type
- baseline_ref/hash
- candidate_ref/hash
- case_set_ref/hash
- frozen_criteria_ref/hash
- resource budget
- timeout
- permission/network policy
- workspace/ref optional
- environment/version refs

spec 자체를 immutable artifact/hash로 남긴다.

## Runner/adapters

core runner는 target-specific detail을 모른다.

- prompt/config adapter
- code/repo adapter
- pipeline/policy adapter

unsupported target은 명시적 unsupported failure다.

## Isolation

### Code

- disposable worktree/workspace
- production working tree overwrite 금지
- production credential 미주입
- filesystem/network permission explicit
- timeout/output cap
- cleanup 검증
- candidate가 evaluator/case fixture/protected config를 건드리면 experiment invalid/protected

### Prompt/config

- versioned candidate ref
- production alias 미변경
- baseline/candidate 동일 input set

## Reproducibility

Result에:

- exact spec hash
- baseline/candidate refs
- environment/dependency refs
- per-case outcome refs
- common/dynamic evidence
- artifacts/log refs
- failure reason

을 남긴다.

## Requirements

| ID | 요구 | 검증 |
|---|---|---|
| 03C-01 | candidate failure가 production target에 영향 없음 | isolation negative |
| 03C-02 | baseline/candidate 동일 frozen cases | hash assertion |
| 03C-03 | criteria tamper가 evaluation invalid 처리 | tamper fixture |
| 03C-04 | timeout/process cleanup | process integration |
| 03C-05 | production secret 접근 없음 | canary/permission |
| 03C-06 | result reproducible refs 보존 | rerun fixture |

## 완료조건

ordinary proposal이 production과 credential을 분리한 sandbox에서 frozen criteria/case로 재현 가능한 비교를 거쳐야 한다.
