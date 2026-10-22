# Stage 1.4 — Runtime Placement and Tool Surface

2026-10-21 DP7 실행기 보정: **개발중**(관제 재등록·운영 검증 대기). Interactive 등록·1분 재기동, WinGet agy 탐색, 작업자별 실패 진단·fallback을 수정했다. 관련 64 passed, 전체 747 passed / 69 skipped / 기존 OpenCode smoke 1 failed. [근거·운영 명령](../../dp7-loop.md#2026-10-21-work-실패무변경-깨어남-보정).

## Status

- 2026-10-23 API health 감시: **개발완료**(코드·회귀시험). API와 독립된 분당 예약 작업으로 3회 연속 실패 시 진단 후 재시작하며, 1시간 3회 한도 이후 자동 복구 중단·보고를 적재한다. 관제 재등록·실제 복구 확인은 남았다. [조사·운영 기록](../../overseer-plan.md#2026-10-23-중앙-api-무응답-감시).

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: Stage 0 완료
- contracts: ../plan-verification-contract.md, ../data-security-artifact-contract.md

Stage 0 gate가 활성인 동안 04B/04C를 포함한 Stage 1 구현을 시작하지 않는다. child 상태도 parent와 일치시킨다.

2026-09-27 사용자 요청으로 [네 로컬 worker 연결](../../worker-adapters.md)을 한정 선행 작업으로 완료했다(네 CLI 실제 파일 생성 확인). 해당 연결은 기존 WorkerService의 호스트 실행 경로이며, 04B의 전체 계약이나 04C workspace resolver의 완료 판정으로 확대하지 않는다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 04A | LiteLLM + PydanticAI Model Wiring | 개발중 | 아니오 | Stage 0 |
| 04B | Codex Worker | 개발중 | 아니오 | Stage 0 |
| 04C | Laptop Workspace Resolver | 개발중 | 아니오 | Stage 0 |
| 04D | AWS Single-Node Runtime | 개발중 | 아니오 | Stage 0 + 01 + 04A |
| 04E | Laptop Approval Authority | 개발중 | 아니오 | 03 + 04D security boundary |
| 04F | Artifact Store & Integrity | 개발중 | 아니오 | Stage 0 + 01 |
| 04G | Secrets / Operations / Dependency Security | 개발중 | 아니오 | Stage 0 + 04D |

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

## 2026-10-21 상태 정정

기존 부품의 존재와 단위시험을 Stage 전체 운영 완료로 표시하지 않는다. [DP7 자기개선 고리](../../dp7-loop.md)에 연결 경로와 남은 검증을 기록했다. 메타인지→영속 Work→사본 실행→시험→반영/되돌림→Event→다음 관측→보고 적재를 연결했다. 실제 DB·Discord·재부팅 검증은 확인 전이다. 서버와 실행기는 DP7, 노트북은 기록 전용이다. 기존 일일 보고 composer나 보호 변경 승인 경계 전체를 완료한 것은 아니다.

## 2026-10-21 DP7 Windows Selector 수정

이벤트 루프 수정 상태: **개발완료**. Stage 1 전체는 **개발중**을 유지한다. API·executor·overseer 및 수동 metacog는 Windows Selector를 사용하고, 작업자 subprocess는 별도 스레드 Proactor에서 실행한다. collect --no-metacog는 PostgreSQL을 사용하지 않는다.

검증: 관련 **26 passed**, 전체 **728 passed, 69 skipped, 1 failed**. 실패는 기존 외부 npx/OpenCode help 실행이다. 실제 DB SELECT 1과 임시 API /healthz HTTP 200을 확인했다. 기존 5476 예약 작업은 재시작하지 않았다. 상세 기록은 docs/dp7-loop.md에 있다.
