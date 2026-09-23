# 05A — Report Projection and Store

## Status

- 상태: **선행작업 대기**
- 선행조건: 02 Researcher Loop 완료
- 지금 시작 가능: **아니오**

## 목적

Event dump가 아니라 bounded source-backed operational report projection을 durable하게 저장한다.

## Report identity

reports:

- report_id
- user_id
- logical_period_id
- timezone
- period_start_utc / period_end_utc
- projection_version
- input_watermark/hash
- revision
- supersedes_report_id optional
- status: DRAFT / FINAL
- summary
- sections
- source_refs
- created_at / finalized_at

idempotency key:
user_id + logical_period_id + projection_version + input_watermark/hash

FINAL report는 immutable하다.
FINAL 이후 late source Event가 해당 period에 포함되어야 하면 기존 row를 덮지 않고 새 revision을 만들고 supersedes_report_id로 연결한다.

## Projection input

- autonomous/user Goal 상태 변화
- Work/Run 결과
- research ArtifactRefs
- improvement proposed/promoted/rejected/rollback
- protected pending proposals
- pending Questions
- resource/cost summary
- priority/yield events

raw Event 전체나 raw prompt를 report row에 복제하지 않는다.

## Unknown

cost/result가 unknown이면 UNKNOWN으로 보존한다. 0/empty로 변환하지 않는다.

## Requirements

- 같은 exact input watermark 재생성 → same report/ref
- late event → revision, prior FINAL immutable
- source refs가 owner/access scope를 유지
- report row에서 raw secret/content canary 부재
- restart 후 report identity/revision 보존

## 완료조건

동일 입력에 idempotent하고 late evidence에도 history를 덮어쓰지 않는 durable report projection이어야 한다.
