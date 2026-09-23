# 3.4B — Milestone / Artifact Progress

## 구현 위치
- 새: src/all_tomorrow/milestones.py
- migration: migrations/00xx_milestones.sql
- tests: tests/test_milestones.py

Goal 시작 시 versioned milestone/evaluation plan.
progress는 Outcome + immutable ArtifactRefs + tests.
Work count/token/file count는 activity metric.

Requirements:
- S3-34B-01 milestone criterion freeze/version
- S3-34B-02 artifact hash/source/license provenance
- S3-34B-03 activity-only progress reject
