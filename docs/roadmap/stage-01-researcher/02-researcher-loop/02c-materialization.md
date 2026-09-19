# 02C — Researcher Decision Materialization

## Status

- 상태: **선행작업 대기**
- 선행조건: 02B 완료
- 지금 시작 가능: **아니오**
- 완료 후 열림: 02D Lineage & Dedup

## 목적

Researcher model output을 검증된 durable Goal/Work/Question/Proposal mutation으로 변환한다.

## 수정 파일

- 수정: `src/all_tomorrow/researcher.py`
- 수정: `src/all_tomorrow/storage/postgres.py`
- 수정: `src/all_tomorrow/work.py`
- 수정: `src/all_tomorrow/evaluation.py`
- 새 테스트: `tests/test_researcher_materialization.py`

## Materializer

class:

`ResearcherDecisionMaterializer`

method:

- `apply(snapshot, decision)`

모든 mutation은 model output을 그대로 SQL로 연결하지 않고 typed contract로 변환.

## Action mapping

### NOOP

- DB mutation 없음
- `researcher.noop` Event

### CREATE_GOAL

- origin=`researcher`
- objective/title/priority validation
- Goal 생성
- 필요하면 root Work 함께 생성
- `goal.autonomous_created` Event

### CREATE_WORK

- existing Goal 검증
- parent/evidence lineage
- priority/budget inherit
- trace lineage 결정
- Work 생성
- `work.autonomous_created`

### REVISE_WORK

1차에서는 기존 Work payload를 제자리에서 조용히 덮지 않는다.

- 기존 Work가 terminal이면 새 child/successor Work 생성
- non-terminal이면 revision 증가 + Event
- 이유/evidence refs 필수

### ASK_USER

현재 Pipeline UserQuestion과 같은 resume-token 구조를 억지로 재사용하지 않는다.

Stage 1 researcher question은 Work를 WAITING으로 만들고 pending question record를 연결할 수 있도록 durable question primitive를 Goal/Work 레벨로 일반화한다.

01 구현 결과를 보고 기존 user_questions를 확장하거나 별도 work_questions를 추가한다.

### PROPOSE_IMPROVEMENT

03의 `ImprovementProposal` persistence로 넘김.

03이 아직 구현 전이면 typed proposal candidate를 Event/Work로 남길 수 있지만 production change는 금지.

## Atomicity

Goal/Work 생성 + provenance Event는 같은 transaction.

CREATE_GOAL + initial Work를 함께 만들면 둘도 같은 transaction.

## 테스트

- autonomous Goal + root Work atomic 생성
- invalid target Goal → mutation 없음
- terminal Work revise → successor 생성
- evidence ref 없이 mutation 거절
- NOOP state change 없음
- improvement proposal은 production mutation 없음

## 하지 말 것

- model 출력 SQL 실행
- model이 지정한 arbitrary status 그대로 수용
- 기존 Work history 삭제/덮어쓰기
- 사용자 질문을 ephemeral memory에만 저장

## 완료조건

모델 decision이 typed durable state로 materialize되고 모든 mutation에 origin/evidence/provenance가 남음.
