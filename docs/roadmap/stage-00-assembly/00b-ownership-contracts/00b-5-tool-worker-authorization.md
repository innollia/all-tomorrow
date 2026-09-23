# 00B-5 — Tool / Worker / Authorization Boundary

## Status
- 상태: 선행작업 대기
- 선행조건: 00B-2 + 00A gateway result
- 완료 후 열림: Stage 1 runtime/tool packets

## 목적
Tool Gateway transport와 All Tomorrow authorization/descriptor authority를 분리한다.

## 구현 예정 위치
- 새: src/all_tomorrow/tools/registry.py
- 새: src/all_tomorrow/authorization.py
- 수정 후보: src/all_tomorrow/adapters/workers.py
- config: config/authority-policy.example.yaml
- 테스트: tests/test_authorization.py
- 테스트: tests/test_tool_registry.py

## Canonical registry
LiteLLM/FastMCP registry를 정본으로 쓰지 않는다.
All Tomorrow는 ToolDescriptor/WorkerDescriptor metadata를 소유한다.

## Authorization
일반 external action도:
- actor
- target/source
- requested capability
- risk class
- ALLOW/CONFIRM/DENY
- policy version
을 남긴다.

protected self-change는 03E/04E의 더 강한 boundary를 사용한다.

## Untrusted content
retrieved docs/README/tool output가 tool permission이나 system instruction을 확대하지 못한다.

## Requirements
- S0-00B5-01: gateway transport registry와 canonical descriptor 분리
- S0-00B5-02: read/write/delete/push 같은 capability authorization
- S0-00B5-03: untrusted content가 authority를 확대하지 못함
- S0-00B5-04: 새 tool/worker 추가에 core name branch 없음

## 완료 증거
- descriptor schema
- authority matrix
- selected gateway mapping
- deny/confirm negative fixtures
