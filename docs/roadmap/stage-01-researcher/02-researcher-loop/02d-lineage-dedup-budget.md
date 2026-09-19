# 02D — Autonomous Lineage, Dedup and Budget

## Status

- 상태: **선행작업 대기**
- 선행조건: 02C 완료
- 지금 시작 가능: **아니오**
- 완료 후 열림: 02E Researcher Acceptance

## 목적

특정 문제 taxonomy나 임의 depth=2 같은 규칙 없이 autonomous Work 폭주를 막는다.

## 수정 파일

- 수정: `src/all_tomorrow/researcher.py`
- 수정: `src/all_tomorrow/work.py`
- 수정: `src/all_tomorrow/storage/postgres.py`
- 새 테스트: `tests/test_researcher_limits.py`

## Autonomous lineage

모든 researcher-created Goal/Work에:

- origin
- parent Goal/Work optional
- root autonomous lineage id
- source snapshot id
- evidence refs
- created_at

를 남긴다.

## Budget

lineage별 공통 budget:

- max Work count
- max model tokens/cost
- max wall-clock age
- max concurrent RUNNING count

값은 config/policy에서 온다.

문제 종류별 quota는 만들지 않는다.

budget exhaustion:

- 새로운 autonomous child 생성 중단
- 기존 durable state 삭제하지 않음
- `researcher.lineage_budget_exhausted` Event
- 필요하면 다음 wake에서 재평가

## Dedup

새 Goal/Work 생성 전에 deterministic fingerprint 계산:

입력:

- normalized action type
- target Goal/project
- short objective/title
- evidence refs
- relevant target id

같은 fingerprint의 open Work가 있으면 새 Work를 만들지 않고 기존 Work ref 사용.

semantic embedding dedup은 1차 필수 아님.

## Wake dedup

동일 trigger id/event cursor 범위를 동시에 여러 researcher instance가 처리하지 못하도록 observer cursor/lease 사용.

## Test

- 같은 decision 두 번 materialize → Work 하나
- 다른 evidence면 별도 Work 가능
- lineage Work cap 초과 시 생성 중단
- cost budget 초과 시 LLM call/child 생성 중단
- concurrent wake 하나만 같은 cursor range 처리
- depth가 깊어도 budget 안이면 허용

## 하지 말 것

- max_depth=2 같은 arbitrary recursion hardcode
- 실패 유형별 생성 제한
- embedding/vector DB 필수화
- budget 초과 시 기존 Work 자동 삭제

## 완료조건

autonomous recursion이 generic resource budget으로 유한하고, 동일 관찰에서 duplicate Work storm이 발생하지 않음.
