# Stage 1.4 — Runtime Placement and Tool Surface

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 integration seam 확정

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 04A | LiteLLM + PydanticAI Model Wiring | 선행작업 대기 | 아니오 | Stage 0 | [04a](04-runtime-and-tools/04a-litellm-gateway.md) |
| 04B | Codex Worker | 선행작업 대기 | 아니오 | Stage 0 worker seam 확인 | [04b](04-runtime-and-tools/04b-codex-worker.md) |
| 04C | Laptop Workspace Resolver | 선행작업 대기 | 아니오 | Stage 0 ownership 확인 | [04c](04-runtime-and-tools/04c-laptop-workspace.md) |
| 04D | AWS Single-Node Runtime | 선행작업 대기 | 아니오 | 01 + 04A | [04d](04-runtime-and-tools/04d-aws-runtime.md) |
| 04E | Laptop Approval Authority | 선행작업 대기 | 아니오 | 03 | [04e](04-runtime-and-tools/04e-approval-authority.md) |

## 원칙

Runtime & Tools의 목적은 framework를 늘리는 것이 아니라 이미 존재하는 substrate와 기존 worker를 연결하는 것이다.

- LiteLLM client 중복 구현 금지
- durable queue 중복 구현 금지
- worker CLI adapter는 고유 protocol 때문에 유지 가능
- project-local workspace와 source identity 분리 유지
- Approval Authority는 외부 보안 경계 유지
