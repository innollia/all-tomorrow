# 2.3D — Repair / Operator Workflow

## 구현 위치
- 새: src/all_tomorrow/repair.py
- 수정: control API
- tests: tests/test_repair.py

## Surface
REPAIR_REQUIRED list/inspect/retry/reconcile/resolve/abandon.
operator action은 Authorization+Event.
blind retry 불가 side-effect는 explicit resolution 필요.

## Requirements
- S2-23D-01 reconciliation exhausted record 보존
- S2-23D-02 safe retry capability 검사
- S2-23D-03 operator resolution audit
- S2-23D-04 repair가 original provenance 삭제 안 함
