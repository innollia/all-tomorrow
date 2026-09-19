# 05A — Report Projection and Store

## Status

- 상태: **선행작업 대기**
- 선행조건: 02 Researcher Loop 완료
- 지금 시작 가능: **아니오**

## 목적

Event dump가 아니라 사용자에게 보여줄 일일 운영 요약의 durable source를 만든다.

## 수정 파일

- 새 migration: `migrations/0006_reports.sql`
- 새 파일: `src/all_tomorrow/reports.py`
- 새 파일: `src/all_tomorrow/storage/report_store.py`
- 수정: `src/all_tomorrow/storage/postgres.py`
- 새 테스트: `tests/test_reports.py`

## reports table

- report_id PK
- user_id
- period_start
- period_end
- status: DRAFT / FINAL
- summary text
- sections jsonb
- source_refs jsonb
- created_at

unique:

- user_id + period_start + period_end + version 또는 report_idempotency_key

## ReportInput projection

조회 대상:

- autonomous Goal 생성/상태 변화
- autonomous Work 상태 변화
- research 결과 refs
- improvement proposed/promoted/rejected/rolled_back
- protected pending proposals
- pending user questions
- resource/cost summary
- user-priority preemption events

raw Event 전체를 report에 붙이지 않는다.

## Idempotency

같은 period를 반복 생성해도 duplicate final report를 무한히 만들지 않는다.

source watermark/version으로 동일 입력이면 기존 report 반환 가능.

## 완료조건

하루치 상태를 bounded source refs와 함께 durable report record로 저장 가능.
