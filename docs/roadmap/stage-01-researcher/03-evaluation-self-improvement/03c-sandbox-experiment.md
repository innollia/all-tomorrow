# 03C — Generic Sandbox Experiment

## Status

- 상태: **선행작업 대기**
- 선행조건: 03A + 03B 완료
- 지금 시작 가능: **아니오**
- 추가 의존성: repo/code change는 04C workspace + coding worker 사용 가능

## 목적

proposal 종류별 전용 optimizer를 만들지 않고 baseline과 candidate를 bounded environment에서 비교한다.

## 수정 파일

- 새 파일: `src/all_tomorrow/experiments.py`
- 수정: `src/all_tomorrow/evaluation.py`
- 새 테스트: `tests/test_experiments.py`

## ExperimentSpec

- proposal_id
- target_type
- baseline_ref
- candidate_ref
- cases/evidence source refs
- budget
- timeout
- permissions
- workspace/ref optional
- evaluator criteria ref

## ExperimentRunner

target-specific 실행은 adapter로 분리:

- prompt/config experiment adapter
- code/repo experiment adapter
- pipeline policy adapter

core runner는 target_type 이름별 구현 내용을 알지 않고 adapter registry로 capability resolve.

## Isolation

code change:

- temporary branch/worktree 또는 disposable workspace
- production working tree 직접 overwrite 금지
- tests/evaluation command bounded
- timeout
- output cap

prompt/config:

- versioned candidate ref
- production alias를 먼저 바꾸지 않음

## Result

- baseline outcome refs
- candidate outcome refs
- common metric evidence
- dynamic evidence
- artifacts/log refs
- failure reason

raw secret를 result metadata에 넣지 않는다.

## 테스트

- candidate failure가 production target에 영향 없음
- timeout cleanup
- baseline/candidate 동일 case set
- artifact refs/provenance
- unsupported target → explicit failure, core branch 추가 아님

## 완료조건

ordinary proposal이 production 변경 전 reproducible bounded comparison을 거침.
