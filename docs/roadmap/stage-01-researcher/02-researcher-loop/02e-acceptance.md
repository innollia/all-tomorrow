# 02E — Researcher Loop Acceptance

## Status

- 상태: **선행작업 대기**
- 선행조건: 02A~02D 완료
- 지금 시작 가능: **아니오**

## 필수 scenarios

| ID | Scenario | 실패 조건 |
|---|---|---|
| 02E-01 | 정상/새 observation 없음 → NOOP | 의미 없는 Goal/Work 생성 |
| 02E-02 | unlabeled repeated failure → investigation Work | 원인을 fixture metadata에서 직접 읽거나 evidence 없이 단정 |
| 02E-03 | open Work 정체 + evidence → 진단/후속 Work | 기존 Work history overwrite |
| 02E-04 | 이전 researcher decision/result 재관찰 | self history 누락 |
| 02E-05 | autonomous Goal | source evidence/expected outcome 없는 무목적 Goal |
| 02E-06 | same observation concurrent/replay | duplicate Work |
| 02E-07 | budget exhaustion | ceiling 초과 또는 Work storm |
| 02E-08 | malformed output | state mutation 발생 |
| 02E-09 | researcher process restart | cursor/lineage 손실 |
| 02E-10 | generated investigation completion | 결과 artifact/evidence 또는 explicit inconclusive outcome 없이 activity만 생성 |

## Autonomous value gate

"가치 있는 문제"를 모델 자기평가 한 문장으로 통과시키지 않는다.

autonomous Goal/Work는 최소:

- observation evidence
- expected outcome 또는 question
- bounded budget
- completion/evaluation criterion

을 가진다.

02E-10에서는 최소 하나의 investigation Work를 terminal outcome까지 실행해 다음 중 하나를 남긴다.

- evidence-backed finding ArtifactRef
- reproducible failure characterization
- explicit inconclusive result + why

단순 Work 생성 수는 성공 metric이 아니다.

## Evidence level

- schema/decision: L0
- PostgreSQL dedup/budget/cursor: L1
- restart: L2

## 완료 시

- 02A~02E 및 parent 02 상태 갱신
- 03 선행조건 재계산
- 05 선행조건 재계산
