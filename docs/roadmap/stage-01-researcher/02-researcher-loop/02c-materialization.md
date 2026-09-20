# 02C — Researcher Decision Materialization

## Status

- 상태: **선행작업 대기**
- 선행조건: 02B 완료
- 지금 시작 가능: **아니오**
- 완료 후 열림: 02D
- contracts: ../../domain-contracts.md, ../../plan-verification-contract.md

## 목적

validated typed decision을 durable Goal/Work/Question/Proposal state로 materialize한다.

## Core rule

model payload를 SQL/domain object에 그대로 복사하지 않는다.
action별 validator → canonical domain command → transaction 순서다.

## Action mapping

### NOOP

- state mutation 없음
- researcher.noop Event

### CREATE_GOAL

한 transaction:

- Goal(origin=researcher)
- 필요 시 root Work
- lineage/evidence refs
- Event

### CREATE_WORK

- target Goal ownership/state 검증
- parent/evidence lineage
- budget reservation 확인
- Work + Event atomic

### REVISE_WORK

- terminal Work: in-place revive 금지, successor Work 생성
- non-terminal Work: allowed semantic fields만 revision 증가
- arbitrary status 변경 금지
- reason/evidence 필수

### ASK_USER

canonical Question contract를 사용한다.

- Question durable record 생성
- Work를 semantic WAITING으로 transition
- backend durable wait/signal correlation 생성
- duplicate decision/question_id는 record 1개
- answer 저장과 signal 전송은 idempotent

기존 user_questions schema가 contract를 만족하면 확장하고, 아니면 migration을 추가한다. 저장 의미는 이 packet에서 더 이상 미정이 아니다.

### PROPOSE_IMPROVEMENT

03A store가 있으면 ImprovementProposal 생성.
03A 전이면 immutable typed proposal candidate + Event만 남기며 production mutation 금지.

## Atomicity / idempotency

- Goal/Work/Question/Proposal mutation + provenance Event는 application transaction으로 묶음
- decision_id 또는 materialization_key에 DB unique constraint를 둬 같은 decision replay가 duplicate mutation을 만들지 않음
- Event만 성공하고 domain mutation이 실패하거나 그 반대인 partial commit 금지

## Requirements

| ID | 요구 | 검증 | Level |
|---|---|---|---|
| 02C-01 | same decision 두 번 apply → mutation 1개 | concurrent/replay integration | L1 |
| 02C-02 | CREATE_GOAL + root Work + Event atomic | transaction failure test | L1 |
| 02C-03 | terminal Work revise → successor | domain integration | L1 |
| 02C-04 | invalid target/evidence → mutation 0 | negative | L0/L1 |
| 02C-05 | ASK_USER durable + duplicate safe | restart/replay | L2 |
| 02C-06 | proposal candidate가 production change를 직접 만들지 않음 | architecture/negative | L0 |

## 완료조건

모든 decision action이 canonical typed state로 atomic/idempotent하게 materialize되고 origin/evidence/provenance를 가진다.
