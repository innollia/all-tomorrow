# 3.1B — School Artifact Pipeline

## 선행
3.1A + Stage2 Artifact

## 구현 위치
- 새: src/all_tomorrow/personal/school.py
- tests/integration/test_school_artifact.py

Flow:
upload ArtifactRef→extraction ArtifactRef→classification→owner/ref→Goal/Work.

page/range provenance, extraction version, confidence/unknown regions.
duplicate artifact hash dedup.

Requirements:
- S3-31B-01 original→extraction→Work lineage
- S3-31B-02 low-confidence region fabricated fact 금지
- S3-31B-03 raw document telemetry 복제 금지
