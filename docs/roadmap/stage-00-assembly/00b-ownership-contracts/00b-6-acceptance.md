# 00B-6 — Ownership Contract Acceptance

## Status
- 상태: 선행작업 대기
- 선행조건: 00B-1~00B-5

## 목적
00B를 문서 합의가 아니라 executable contract set으로 닫는다.

## Acceptance
- identity/state contract tests
- port fake/alternate adapter tests
- CanonicalError normalization
- DeliveryRecord state/reconciliation model
- retry policy no-unresolved-cell
- tool/worker authorization fixtures
- Stage 1 schema/doc consistency scan

## Requirements
- S0-00B6-01: 00B-1~5 requirement evidence complete
- S0-00B6-02: unresolved placeholder 0, 단 00E로 명시 위임된 exact deployment value 제외
- S0-00B6-03: 01A~01D가 identity/port/delivery contract와 충돌하지 않음
- S0-00B6-04: wrong-implementation fixtures 실제 실패

## 완료 후
00B parent와 index를 개발완료로 갱신하고 00C 시작 가능 상태를 계산한다.
