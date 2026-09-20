# All Tomorrow Roadmap

이 파일은 master status index다. 세부 구현 계획을 여기에서 읽지 않는다.

## Current Position

| Stage | 상태 | 지금 시작 가능 | 선행조건 | 상세 |
|---|---|---:|---|---|
| 0. OSS Assembly & Architecture Proof | 개발중 | 예 | 없음 | [status/index](roadmap/stage-00-assembly/index.md) |
| 1. Durable Self-Improving Researcher | 선행작업 대기 | 아니오 | Stage 0 완료 | [status/index](roadmap/stage-01-researcher/index.md) |
| 2. Reliable Assistant & Remote Control | 선행작업 대기 | 아니오 | Stage 1 완료 | [status/index](roadmap/stage-02-assistant/index.md) |
| 3. Personal Manager & Generalized Autonomy | 선행작업 대기 | 아니오 | Stage 2 완료 | [status/index](roadmap/stage-03-manager/index.md) |

## 지금 바로 작업 가능한 것

Stage 0만 진행한다.

- OSS substrate spike
- All Tomorrow와 외부 엔진의 ownership boundary 확정
- 실제 PostgreSQL을 포함한 crash/restart walking skeleton
- observability/eval/CI seam 검증
- 결과에 따라 Stage 1 schema와 packet을 확정

Stage 0가 끝나기 전에는 새 durable queue, lease/heartbeat, LLM client, agent framework를 직접 구현하지 않는다.

## 제품 완성 순서

Stage 0는 제품이 아니라 기반 선택과 실패 검증 단계다.

1. Researcher
2. Reliable assistant
3. Personal manager

## Assembly Rule

All Tomorrow는 범용 인프라를 다시 구현하는 프로젝트가 아니다.

직접 소유하는 것:
- Goal/Work의 사용자·프로젝트 의미
- project/source ownership과 context assembly
- planner/metacognition policy
- authority와 protected-change boundary
- 외부 실행을 연결하는 provenance

우선 외부 엔진에 위임하는 것:
- PydanticAI: agent/tool/MCP/structured-output/eval interface
- Stage 0에서 선택된 durable backend: execution journal/recovery/signal mechanics
- LiteLLM: model/provider gateway
- OpenTelemetry: telemetry contract
- GitHub/Actions: code change와 CI/evaluation rail

후보를 동시에 중복 도입하지 않는다. Hatchet/Temporal 등은 migration candidate로 유지하고, Stage 0에서 adapter boundary를 증명한다.

## 필요한 문서만 읽기

- 현재 기반 선택: [Stage 0](roadmap/stage-00-assembly/index.md)
- 작업 파일 찾기: [roadmap file map](roadmap/README.md)
- 00B 이후 공통 작성/완료 기준: [plan verification contract](roadmap/plan-verification-contract.md)
- identity/state: [domain contracts](roadmap/domain-contracts.md)
- failure/recovery: [failure recovery contract](roadmap/failure-recovery-contract.md)
- data/security/artifact: [data security artifact contract](roadmap/data-security-artifact-contract.md)
- 구조/권한 변경 작업만: [cross-stage invariants](roadmap/invariants.md)
- 원문 요구 누락 감사만: [vision coverage](roadmap/vision-coverage.md)
- 확정된 OSS 조립 원칙: [ADR 0005](decisions/0005-assemble-open-source-substrates.md)

## 상태 정의

- **개발중**: 현재 구현/수정 중
- **개발완료**: 해당 파일 Done When 실제 충족
- **시작안했음**: 선행조건은 충족됐지만 미착수
- **선행작업 대기**: 다른 작업 완료 전 착수하지 않음

파일이나 prototype이 존재한다는 이유만으로 개발완료로 표시하지 않는다.
