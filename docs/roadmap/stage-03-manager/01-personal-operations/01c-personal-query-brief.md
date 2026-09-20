# 3.1C — Personal Query & Brief Projection

## 선행
3.1A

## 구현 위치
- 새: src/all_tomorrow/personal/context.py
- 새: src/all_tomorrow/personal/brief.py
- tests: tests/test_personal_context.py

central Work + owner schedule/task/school refs + freshness를 ContextPack에 조립.
brief는 Trigger/OutboundDelivery를 재사용.

Requirements:
- S3-31C-01 "뭐 해야 돼?" source-backed answer
- S3-31C-02 stale/unknown 표시
- S3-31C-03 proactive brief idempotent outbound
- S3-31C-04 owner truth 중앙 복제 최소화
