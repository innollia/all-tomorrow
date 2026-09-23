# 3.4D — Artifact-bound Feedback & Follow-up

## 구현 위치
- 새: src/all_tomorrow/feedback.py
- tests: tests/test_feedback.py

feedback는 exact artifact/build hash에 bind.
explicit feedback→evaluation→successor Work.
preference hypothesis가 explicit feedback을 대체하지 않음.

Requirements:
- S3-34D-01 wrong artifact feedback 적용 금지
- S3-34D-02 feedback→follow-up lineage
- S3-34D-03 explicit command priority
