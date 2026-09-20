# Stage 1.4 — Runtime Placement and Tool Surface

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 완료
- contracts: ../plan-verification-contract.md, ../data-security-artifact-contract.md

Stage 0 gate가 활성인 동안 04B/04C를 포함한 Stage 1 구현을 시작하지 않는다. child 상태도 parent와 일치시킨다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 04A | LiteLLM + PydanticAI Model Wiring | 선행작업 대기 | 아니오 | Stage 0 |
| 04B | Codex Worker | 선행작업 대기 | 아니오 | Stage 0 |
| 04C | Laptop Workspace Resolver | 선행작업 대기 | 아니오 | Stage 0 |
| 04D | AWS Single-Node Runtime | 선행작업 대기 | 아니오 | Stage 0 + 01 + 04A |
| 04E | Laptop Approval Authority | 선행작업 대기 | 아니오 | 03 + 04D security boundary |

## 원칙

- custom model/provider client 중복 구현 금지
- durable queue/recovery 중복 구현 금지
- worker CLI adapter는 CLI protocol 차이만 흡수
- project identity와 host-local workspace 분리
- AWS와 laptop credential/authority domain 분리
- runtime/deployment도 evidence level과 rollback path를 가진다
