# 00E — Architecture Lock & Stage 1 Rewrite

## Status

- 상태: **선행작업 대기**
- 선행조건: 00A~00D
- 공통 계약:
  - ../plan-verification-contract.md
  - ../domain-contracts.md
  - ../failure-recovery-contract.md
  - ../data-security-artifact-contract.md

## 목적

spike 결과를 architecture decision과 Stage 1 실행 계획으로 동결한다.
00E는 단순 기록 단계가 아니라 Stage 1의 모든 packet이 더 이상 Stage 0 결과를 추측하지 않도록 만드는 rewrite gate다.

## Decision record 형식

각 architecture 결정은 최소 다음을 가진다.

- decision id/title
- chosen option + exact version
- consumption mode: package/container/protocol/fork
- observed evidence refs/test ids
- rejected alternatives와 실제 기각 이유
- owned/non-owned state
- failure/retry owner
- data/retention impact
- upgrade compatibility constraint
- rollback/escape condition
- migration trigger
- downstream packets affected

"선호한다/쓸 예정이다"만 있는 기록은 확정 결정이 아니다.

## 반드시 닫을 결정

1. selected durable backend + exact version
2. run_id → external identity mapping
3. upgrade strategy: direct replay 또는 blue/green/drain 등 실제 검증된 방식
4. model retry primary owner
5. tool transport retry primary owner
6. priority/delay/signal/cancel mapping
7. LiteLLM MCP Gateway 채택 여부
8. FastMCP fallback 필요 여부
9. LiteLLM persistence/logging on/off + retention
10. durable journal data classification/retention/backup
11. artifact storage/ref strategy
12. existing PipelineRuntime: maintain / compatibility-only / retire
13. AWS 최소 process topology
14. protected approval credential boundary

## Stage 1 rewrite requirements

Stage 1 문서 전체를 다음 기준으로 다시 검사한다.

### Identity/schema

- Work에는 단일 ExecutionRef를 두지 않음
- Run이 ExecutionRef 소유
- Work 1:N Run
- Run state는 semantic attempt state이며 backend status 복사 아님
- canonical Question/Artifact refs 사용

### 제거

- custom queue claim/lease/heartbeat/requeue
- custom durable retry/recovery ownership
- substrate 내부 state/schema 복제
- custom LiteLLM raw provider client
- provider/project 이름별 generic-core branch

### 구체화

- selected adapter mapping
- actual retry policy
- actual process/runtime layout
- crash barrier와 acceptance level
- V1→V2 history handling
- artifact/data retention
- CI required lanes
- approval threat model

## Backend-specific lock

### DBOS 선택 시

기록/검증:

- application version과 in-flight workflow 관계
- persisted serializer/output classification
- custom serializer/encryption 사용 시 round-trip/tooling compatibility
- single-node 시 Conductor 비의존성
- backup/restore procedure
- multi-host/HA trigger가 생겼을 때 Conductor/Temporal/Hatchet 재검토 조건

### Restate 선택 시

기록/검증:

- 라이선스/서비스 제한과 실제 사용 형태
- journal/state serialization/retention
- single-node backup/restore
- application PostgreSQL과 state ownership 분리
- 필요한 최소 primitive(service/object/workflow)
- deployment version 변경 중 recovery
- Pydantic integration upgrade compatibility

## Persisted compatibility

compatibility data로 취급:

- agent name
- durable operation/step name
- toolset id
- workflow/service handler identity
- serializer/schema version
- model/tool contract version

일반 tool 추가가 기존 history를 깨지 않도록 stable dynamic tool boundary를 사용하고 snapshot/replay test를 남긴다.

## Requirements

| ID | 요구 | 증거 |
|---|---|---|
| E-ADR-01 | 모든 필수 architecture 결정이 형식에 맞게 닫힘 | ADR set |
| E-REWRITE-01 | Stage 1 모든 packet이 새 contract와 모순 없음 | checklist/grep/plan review |
| E-ID-01 | Work/Run/ExecutionRef schema 계획 일치 | plan/schema fitness |
| E-UP-01 | 실제 upgrade strategy가 C/D tests로 증명됨 | L2 evidence |
| E-RET-01 | journal/gateway/artifact retention 정책 확정 | inventory |
| E-RUNTIME-01 | AWS 최소 topology와 backup/restart 책임 확정 | deployment plan |
| E-ESCAPE-01 | backend 교체 trigger/escape condition 기록 | ADR |

## 완료조건

Stage 1의 각 packet이 직접 구현할 semantic meaning과 외부 OSS mechanism을 섞지 않고, packet별 input/output/failure/evidence가 확정되어 01A를 추측 없이 시작할 수 있어야 한다.

Stage 1 rewrite에 unresolved placeholder가 남아 있으면 00E와 Stage 0를 개발완료로 올리지 않는다.
