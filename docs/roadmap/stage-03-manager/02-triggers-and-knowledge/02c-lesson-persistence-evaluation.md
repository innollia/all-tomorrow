# 3.2C — Lesson Persistence & Evaluation

## 구현 위치
- 새: src/all_tomorrow/knowledge.py
- 새: src/all_tomorrow/storage/knowledge_store.py
- migration: migrations/00xx_lessons.sql
- tests: tests/test_knowledge.py

LessonCandidate→AcceptedLesson.
scope/evidence/contradiction/confidence/freshness/review_at/supersedes.
acceptance policy versioned.

Requirements:
- S3-32C-01 one model statement만으로 accept 금지
- S3-32C-02 conflicting lesson silent merge 금지
- S3-32C-03 stale lesson review/retire
