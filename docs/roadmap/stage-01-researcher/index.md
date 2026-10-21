# Stage 1 — Durable Self-Improving Researcher

## Stage Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: Stage 0 OSS Assembly & Architecture Proof 완료
- Stage 종료 조건: [06-acceptance.md](06-acceptance.md) 통과
- 공통 계약:
  - ../plan-verification-contract.md
  - ../domain-contracts.md
  - ../failure-recovery-contract.md
  - ../data-security-artifact-contract.md

Stage 1 계획은 공통 contract 수준까지 구체화되어 있고, selected substrate/version/mapping은 [ADR 0006 — Stage 0 Architecture Lock](../../decisions/0006-stage0-architecture-lock.md)에서 실제 spike 결과로 확정됐다(아래 표). Stage 0가 개발완료로 전이되기 전에는 구현하지 않는다.

## 작업 상태판

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 상태/상세 인덱스 |
|---:|---|---|---:|---|---|
| 1 | Minimal Durable Kernel | 개발중 | 예 | Stage 0 | [01-durable-kernel.md](01-durable-kernel.md) |
| 2 | Researcher Loop | 개발중 | 예 | 1 + 04A | [02-researcher-loop.md](02-researcher-loop.md) |
| 3 | Evaluation & Self-Improvement | 개발중 | 예 | 2 | [03-evaluation-self-improvement.md](03-evaluation-self-improvement.md) |
| 4 | Runtime & Tool Surface | 개발중 | 예 | Stage 0 | [04-runtime-and-tools.md](04-runtime-and-tools.md) |
| 5 | Daily Report & Priority | 개발중 | 예 | 1 + 2 + runtime | [05-report-and-priority.md](05-report-and-priority.md) |
| 6 | Stage Acceptance | 개발중 | 예 | 1~5 | [06-acceptance.md](06-acceptance.md) |

## 00E에서 확정된 값 (placeholder 해소 완료)

아래 값은 [ADR 0006 — Stage 0 Architecture Lock](../../decisions/0006-stage0-architecture-lock.md)에서 실제 Stage 0 evidence로 확정됐다. Stage 1 packet은 이 값을 추측하지 않고 참조한다.

| placeholder | 확정 값 | 근거 |
|---|---|---|
| selected durable backend/version/package/runtime | DBOS 3.0.0, package 소비, Python worker + application PostgreSQL(별도 durable 서버 없음) | D-LOCK-01 |
| run_id→external execution mapping | `work_id:run_id`; ExecutionRef는 Run 소유(Work에 두지 않음) | D-LOCK-02 |
| retry owner/attempt/timeout/backoff | 유일 자동 retry owner = DBOS model step(최대 6회, 2초 간격); SDK/LiteLLM/semantic retry 0 | D-LOCK-04, D-LOCK-05 |
| priority/delay/signal/cancel mapping | semantic priority → adapter가 backend priority로 변환; typed wait/signal payload; 구체 수치는 01A~01C에서 store와 확정 | D-LOCK-06 |
| history upgrade/replay-or-drain strategy | 호환 변경 = replay, 비호환 = 새 버전 분리 후 drain(expectation 덮어쓰기 금지) | D-LOCK-03 |
| model/tool gateway selection | LiteLLM Proxy 1.101.0(model+fixed MCP 겸용); FastMCP fallback 불필요 | D-LOCK-07, D-LOCK-08 |
| PipelineRuntime disposition | compatibility-only(중복 durability/retry/queue 축소, recipe 가치는 보존) | D-LOCK-12 |
| AWS process topology | 단일 노드 worker + PostgreSQL + 별도 LiteLLM Proxy; image digest pin(latest 금지); L3 인증은 04D | D-LOCK-13 |
| journal/gateway/artifact retention | journal 7일(active/waiting 제외), LiteLLM logging off, artifact CAS + ArtifactRef만 App DB | D-LOCK-09~11 |
| protected credential boundary | AWS runtime env/config에 protected credential 금지(fitness test 강제); threat model은 04E | D-LOCK-14 |

placeholder가 모두 해소됐으므로, Stage 0가 개발완료로 전이되면 Stage 1 packet은 위 값을 근거로 착수할 수 있다.

## Stage 1에서 재구현하지 않는 것

- custom durable queue/lease/heartbeat/requeue
- custom crash recovery engine
- provider별 model client
- backend internal state를 canonical domain으로 복제
- target/provider 이름별 generic-core branch

## 다음 작업

Stage 0는 완료됐다. 현재는 DP7 자기개선 고리의 실제 운영 검증을 준비한다.

2026-10-21 Eve 디스코드 창구: 파일 보고 재전송·질문 Event 답장·봇 선판단 후 중앙 요청·DP7 등록 스크립트를 연결했다. 상태는 **개발중**이며 실제 Discord·Postgres·재부팅 검증은 남았다. 가짜 클라이언트 검증과 운영 명령은 [DP7 고리](../../dp7-loop.md)에 기록한다.

## 2026-10-21 상태 정정

기존 부품의 존재와 단위시험을 Stage 전체 운영 완료로 표시하지 않는다. [DP7 자기개선 고리](../../dp7-loop.md)에 연결 경로와 남은 검증을 기록했다. 메타인지→영속 Work→사본 실행→시험→반영/되돌림→Event→다음 관측→보고 적재를 연결했다. 실제 DB·Discord·재부팅 검증은 확인 전이다. 서버와 실행기는 DP7, 노트북은 기록 전용이다. 기존 일일 보고 composer나 보호 변경 승인 경계 전체를 완료한 것은 아니다.

## 2026-10-21 DP7 Windows Selector 수정

이벤트 루프 수정 상태: **개발완료**. Stage 1 전체는 **개발중**을 유지한다. API·executor·overseer 및 수동 metacog는 Windows Selector를 사용하고, 작업자 subprocess는 별도 스레드 Proactor에서 실행한다. collect --no-metacog는 PostgreSQL을 사용하지 않는다.

검증: 관련 **26 passed**, 전체 **728 passed, 69 skipped, 1 failed**. 실패는 기존 외부 npx/OpenCode help 실행이다. 실제 DB SELECT 1과 임시 API /healthz HTTP 200을 확인했다. 기존 5476 예약 작업은 재시작하지 않았다. 상세 기록은 docs/dp7-loop.md에 있다.
