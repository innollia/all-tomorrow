# Stage 1.4 — Runtime Placement and Tool Surface

## Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 없음
- 병렬 제한: protected promotion activation은 03-evaluation-self-improvement 완료 필요

## Goal

Researcher를 항상 켜진 중앙 runtime에서 돌리되, 1차에 분산 workspace 문제를 과설계하지 않는다.

## Read with

- ../../worker-adapters.md
- approval 관련 변경 시 ../../decisions/0004-self-modification-and-approval-boundary.md

## AWS Role

첫 always-on central runtime.

초기 책임:

- PostgreSQL / central state
- researcher trigger
- model/API work
- background research
- Goal/Work queue
- reports

## Laptop Role

1차 repo mutation의 주 executor.

- logical source → laptop workspace mapping
- local checkout을 실제 cwd로 사용
- multi-host workspace synchronization은 구현하지 않음
- workspace_resolver seam만 유지

노트북은 Approval Authority host이기도 하다.

AWS 본체는 Approval Authority의 secret/signing authority/code-data write 권한을 갖지 않는다.

## Model Gateway

LiteLLM을 model/provider gateway 우선 후보로 둔다.

All Tomorrow가 Goal/Work orchestration authority를 유지하고, LiteLLM은 model/provider 호출과 routing/budget telemetry 아래층에 둔다.

## Worker Surface

현재 기반:

- Antigravity worker
- OpenCode worker

추가 대상:

- Codex non-interactive worker/job execution

provider 고유 protocol은 adapter/gateway 경계에 둔다.

## Deferred

- AWS/laptop/Sol Pi checkout sync
- branch/dirty-state 자동 조정
- 다중 executor workspace 분기
- offline host repository reconciliation

## Done When

1. LiteLLM을 통한 provider/model 호출 seam 검증
2. Antigravity/OpenCode 기존 adapter 유지
3. Codex worker contract와 실제 실행 검증
4. laptop logical-source workspace resolution 동작
5. AWS와 laptop 역할이 credential/authority 관점에서 분리
