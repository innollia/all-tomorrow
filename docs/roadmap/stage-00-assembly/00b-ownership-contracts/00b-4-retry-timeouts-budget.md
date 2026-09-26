# 00B-4 — Retry, Timeout & Replan Policy

## Status
- 상태: **개발완료**
- 지금 시작 가능: **—**
- 선행조건: 00B-2 + 00A results
- 완료 후 열림: 00C/00D

## 목적
provider/LiteLLM/PydanticAI/durable backend/worker/application이 중복 retry하지 않도록 실제 owner와 수치를 확정한다.

## 구현 예정 위치
- 새: config/execution-policy.example.yaml
- 새: src/all_tomorrow/execution_policy.py
- 테스트: tests/test_execution_policy.py

## Operation classes
- model invocation
- read-only tool
- idempotent mutation
- reconcile-before-retry mutation
- worker process
- durable start/reconcile
- user-request semantic replan

## 각 class 필수 값
- primary retry owner
- retryable CanonicalError
- max attempts 또는 max elapsed budget
- per-attempt timeout
- total timeout
- backoff/jitter
- idempotency requirement
- exhausted transition
- telemetry keys

## Replan storm protection
일반 user Work도:
- max logical Run attempts 또는 replan budget
- repeated same-error fingerprint suppression
- budget exhausted → NEED_USER/FAILED/REPAIR_REQUIRED 중 policy result

무한 Run 생성 금지.

## Time
wall-clock deadline과 monotonic timeout 분리.

## Requirements
- S0-00B4-01: failure class당 retry owner 정확히 1개
- S0-00B4-02: nested defaults 합산이 policy ceiling 초과하지 않음
- S0-00B4-03: user Work replan storm upper bound
- S0-00B4-04: unknown cost/elapsed를 0 처리하지 않음

## 완료 증거
- policy configuration: `config/execution-policy.example.yaml`
- policy engine: `src/all_tomorrow/execution_policy.py`
- tests: `tests/test_execution_policy.py` (4 passed)

### Confirmed Policy Snapshot (00A 측정치 반영)

| Operation Class | Primary Retry Owner | Max Attempts | Per-Attempt Timeout | Total Timeout | Backoff | Exhausted Transition |
|---|---|---|---|---|---|---|
| `MODEL_INVOCATION` | durable_backend_step | 4 | 30.0s | 120.0s | 2.0s (jitter) | FAILED |
| `READ_ONLY_TOOL` | tool_adapter | 3 | 10.0s | 30.0s | 1.0s (jitter) | FAILED |
| `IDEMPOTENT_MUTATION` | durable_backend_step | 3 | 15.0s | 45.0s | 1.5s (jitter) | FAILED |
| `RECONCILE_BEFORE_RETRY_MUTATION` | all_tomorrow_reconciler | 3 | 20.0s | 60.0s | 2.0s (jitter) | REPAIR_REQUIRED |
| `WORKER_PROCESS` | worker_adapter | 2 | 120.0s | 240.0s | 5.0s | FAILED |
| `DURABLE_START_RECONCILE` | all_tomorrow_reconciler | 3 | 10.0s | 30.0s | 1.0s (jitter) | REPAIR_REQUIRED |
| `USER_REQUEST_SEMANTIC_REPLAN` | all_tomorrow_planner | 3 (upper bound) | 300.0s | 900.0s | 0.0s | NEED_USER |

