# 00B-2 — Adapter Ports & Error Semantics

## Status
- 상태: 선행작업 대기
- 선행조건: 00B-1 + 00A selection evidence
- 완료 후 열림: 00B-4, 00B-5

## 목적
DurableExecutionPort, AgentExecutionPort, Tool/Worker adapter의 정상/오류 contract를 확정한다.

## 구현 예정 위치
- 새: src/all_tomorrow/ports/durable.py
- 새: src/all_tomorrow/ports/agent.py
- 새: src/all_tomorrow/ports/tools.py
- 새: src/all_tomorrow/ports/workers.py
- 새: src/all_tomorrow/errors.py
- 테스트: tests/contracts/test_ports.py
- 테스트: tests/contracts/test_error_normalization.py

## DurableExecutionPort
- start
- get
- cancel
- signal
- result

각 operation은 CanonicalError 또는 typed result를 사용한다.

## AgentExecutionPort
- typed input/output
- model route ref
- toolset ref
- usage/provenance
- malformed structured output는 success로 보정하지 않음

## ToolDescriptor / WorkerDescriptor
control-plane-contracts.md의 descriptor를 구현 contract로 사용한다.

## Error normalization
backend/provider-specific exception을 최소 category로 normalize한다.
NOT_FOUND와 UNAVAILABLE, TIMEOUT과 AMBIGUOUS_EFFECT를 합치지 않는다.

## Requirements
- S0-00B2-01: same run_id start idempotency
- S0-00B2-02: cancel terminal/missing/unavailable 분리
- S0-00B2-03: duplicate signal_id idempotency
- S0-00B2-04: Pending vs empty result 분리
- S0-00B2-05: backend/vendor exception → CanonicalError mapping
- S0-00B2-06: fake alternate adapter가 같은 contract 통과

## 완료 증거
- protocol/type definitions
- fake adapter contract tests
- selected adapter mapping table
