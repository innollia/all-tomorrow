# 2.3B — Run / Cancel / Replan

## 구현 위치
- 새/수정: src/all_tomorrow/execution.py
- tests: tests/test_execution_service.py
- integration: tests/integration/test_cancel_replan.py

## 핵심
max active Run=1 기본.
same Run crash recovery와 new Run semantic replan 분리.
일반 user Work에도 replan budget 적용.
Goal/Work cancellation propagation.

## Requirements
- S2-23B-01 two active Runs 기본 금지
- S2-23B-02 Run success 후 CompletionEvidence 없으면 Work success 금지
- S2-23B-03 replan storm ceiling
- S2-23B-04 cancel ambiguous effect reconciliation
- S2-23B-05 Goal cancel child/Question/Trigger propagation
