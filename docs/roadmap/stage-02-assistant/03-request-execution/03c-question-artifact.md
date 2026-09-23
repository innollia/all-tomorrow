# 2.3C — Question / Artifact Lifecycle

## 구현 위치
- 새/수정: src/all_tomorrow/questions.py
- artifact store implementation
- migrations: question/artifact tables
- tests: tests/test_questions.py, tests/test_artifacts.py

## Question
PENDING/ANSWERED/SUPERSEDED/CANCELLED/EXPIRED.
replan이 질문을 무효화하면 SUPERSEDED.
late answer는 새 Run 자동 생성 금지.

## Artifact
storage backend를 Stage1/2 시작 전 하나 선택.
temporary upload→hash→finalize→metadata attach.
orphan GC/integrity repair.

## Requirements
- S2-23C-01 answer→signal outbox
- S2-23C-02 superseded late answer 안전
- S2-23C-03 immutable hash fetch
- S2-23C-04 orphan/ref-missing repair
