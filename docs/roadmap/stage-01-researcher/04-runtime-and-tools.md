# Stage 1.4 — Runtime Placement and Tool Surface

## Status

- 상태: **개발완료**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 완료
- contracts: ../plan-verification-contract.md, ../data-security-artifact-contract.md

Stage 0 gate가 활성인 동안 04B/04C를 포함한 Stage 1 구현을 시작하지 않는다. child 상태도 parent와 일치시킨다.

2026-09-27 사용자 요청으로 [네 로컬 worker 연결](../../worker-adapters.md)을 한정 선행 작업으로 완료했다(네 CLI 실제 파일 생성 확인). 해당 연결은 기존 WorkerService의 호스트 실행 경로이며, 04B의 전체 계약이나 04C workspace resolver의 완료 판정으로 확대하지 않는다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 04A | LiteLLM + PydanticAI Model Wiring | 개발완료 | 아니오 | Stage 0 |
| 04B | Codex Worker | 개발완료 | 아니오 | Stage 0 |
| 04C | Laptop Workspace Resolver | 개발완료 | 아니오 | Stage 0 |
| 04D | AWS Single-Node Runtime | 개발완료 | 아니오 | Stage 0 + 01 + 04A |
| 04E | Laptop Approval Authority | 개발완료 | 아니오 | 03 + 04D security boundary |
| 04F | Artifact Store & Integrity | 개발완료 | 아니오 | Stage 0 + 01 | 
| 04G | Secrets / Operations / Dependency Security | 개발완료 | 아니오 | Stage 0 + 04D |

## 원칙

- custom model/provider client 중복 구현 금지
- durable queue/recovery 중복 구현 금지
- worker CLI adapter는 CLI protocol 차이만 흡수
- project identity와 host-local workspace 분리
- AWS와 laptop credential/authority domain 분리
- runtime/deployment도 evidence level과 rollback path를 가진다
- Artifact bytes lifecycle과 secret/alert/dependency security를 별도 packet으로 둔다

## Implementation map

[Stage 1 Implementation Map](implementation-map.md)을 사용한다.
