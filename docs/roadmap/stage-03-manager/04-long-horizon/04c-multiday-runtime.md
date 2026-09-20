# 3.4C — Multi-day Resume & Resource Change

## 선행
3.4A/B + 3.3

## 구현 위치
- 새: src/all_tomorrow/long_horizon.py
- tests/acceptance/test_multiday_goal.py

resume ContextPack은 transcript에 의존하지 않음.
resource offline/quota/provider change→reconcile→new Run→same Goal.

Requirements:
- S3-34C-01 process/day boundary resume
- S3-34C-02 executor switch provenance
- S3-34C-03 resource failure가 milestone/Goal identity 유실 안 함
- S3-34C-04 graph/replan storm budget
