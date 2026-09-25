# 00A-1 — Common Harness

## Status

- 상태: **개발완료**
- 선행조건: 없음
- 완료 기준: [2026-09-20 범위 조정](00a-live-gate-matrix.md)

## 결과

`HarnessInput`, `HarnessOutput`, Work/Run 식별자와 공통 외부 fixture로 두 후보의 typed read → PydanticAI → idempotent mutation → wait/signal 흐름을 비교했다. fixture는 호출 횟수와 실제 적용을 구분한다. 실제 프로세스 종료 및 재기동을 사용했다. 메모리 simulation 결과는 선택 근거에서 제외했다.

모델 저장 전/후 replay, 외부 commit 직후 중복 방지, Work/Run 분리, 승인 재개에 대한 핵심 오해를 해소했다. 후보별 프로세스 제어와 제품 API 호출은 support adapter에 있다. SDK 수준으로 runner를 다시 정리하거나 모든 기존 시험을 하나의 결과 스키마로 이식하는 작업은 선택에 영향을 주지 않으므로 완료조건에서 제외했다.

## 재현과 한계

- 공통 흐름: `tests/test_live_common_d01.py`
- 추가 lifecycle 관측: `tests/test_live_common_lifecycle.py`
- 실제 스택 결합: `tests/test_combined_gateway_agent.py`
- 선택 및 retry/data 계약: [00A-5](00a-5-selection.md)

D01~D12는 기존 실험의 식별자다. 전체 조합을 제품 신뢰성 인증으로 확대하지 않는다. 결과 파일의 옛 partial 상태는 당시 더 넓은 기준에 대한 상태다.
