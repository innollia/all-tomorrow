# Existing System Inventory

조사일: 2026-09-18

> 이 문서는 당시 조사 결과의 historical inventory다. 여기의 `V1`/Phase 표현은 2026-09-18 초기 계획 용어이며, 현재 completion-stage 계획과 우선순위는 `docs/roadmap.md` 및 1차/2차/3차 문서를 따른다.

## 조사 범위와 한계

로컬 `C:\projects`에서 확인 가능한 저장소와 문서를 정적으로 조사했다. AWS, Notion, 실행 중인 서비스와 credential은 이번 단계에서 변경하거나 실시간 검증하지 않았다. 따라서 아래의 운영 상태는 기존 저장소 문서의 주장이고, 현재 시점의 live 사실로 간주하지 않는다.

`eve-scene-runtime`의 로컬 working tree는 최신이 아니었다. 조사 당시 로컬 `main`은 `aad1b373`, 원격 `origin/main`은 `69ceb1aa`였고 로컬은 원격보다 8 commits 뒤였다. 원격을 fetch해 차이를 조사했지만 local branch나 working tree는 checkout/rebase/pull하지 않았다. 아래 inventory는 기본 구조에는 로컬 파일을, 최신 Discord 변경에는 `origin/main`을 함께 사용한 혼합 조사 결과다.

## 저장소 지도

| 경로 | 역할 | Control Plane과의 관계 |
|---|---|---|
| `C:\projects\eve-scene-runtime` | Eve scene/runtime, Notion relay, Discord bot, Manager bridge, MCP server | 가장 중요한 기존 integration source. 도메인 정본은 계속 이 저장소가 소유하고 중앙은 adapter로 호출한다. |
| `C:\projects\nycko_ref` | 별도의 소규모 Discord bot | 현재 중앙화 대상인지 불명. 즉시 통합하지 않는다. |
| `C:\projects\TINProject` | Godot 게임 프로젝트, Antigravity/OpenCode 작업 규칙 | 일반 project 등록 및 lesson 재사용의 향후 검증 후보. Control Plane 코드를 넣지 않는다. |
| `C:\projects\all-tomorrow` | 새 Personal AI Control Plane | 중앙 project/task/run/pipeline/event authority의 소유자. |

## `eve-scene-runtime`에서 재사용할 수 있는 표면

### Discord edge 기반

- `src/discord/bot-agent.mjs`: 현재 Discord 진입점.
- `src/discord/discord-service.mjs`: ACL, 메시지 조회, 검색 등 Discord 접근 규칙을 한곳에 모은 서비스.
- `src/discord/discord-mcp-server.mjs`: Discord 조회 기능을 MCP stdio tool로 노출.
- `src/discord/message-cache.mjs`, `db.mjs`: 로컬 Discord cache와 상태.
- `src/discord/retrieval-budget.mjs`: retrieval 호출/문맥 예산 통제.
- `src/discord/channel-queue.mjs`: 채널 단위 직렬화에 재사용 가능한 패턴.
- 원격 최신 `src/discord/audit-log.mjs`: UUID event/audit ID, timestamp, 본문 hash와 제한된 text를 JSONL로 남기는 신규 audit 표면.
- 원격 최신 Manager/Discord 경로: `audit_id`를 manager turn까지 전달하고 request/completed/failed/boot event를 기록한다.

판정: 새 Discord Gateway client를 만들지 않는다. 조사 당시 초기 edge 범위는 기존 bot에 얇은 adapter를 붙이는 방향을 우선 검토했다. Discord cache는 edge-local cache로 남길 수 있지만 project/task canonical state로 승격시키지 않는다. 최신 `audit_id`는 All Tomorrow의 `trace_id`와 연결할 수 있는 유력한 adapter seam이지만 동일 identifier로 즉시 통합한다고 확정하지 않는다.

### Manager/worker 연결

- `src/discord/manager-bridge.mjs`: Antigravity persistent session의 boot, rollover, timeout, settlement 처리.
- `src/discord/manager-settings.mjs`: 모델/추론/문맥 설정 영속화.
- `src/discord/manager-session-state.mjs`: 현재 manager session 상태.

판정: 조사 당시 초기 범위에서는 Antigravity worker를 새로 구현하지 않고 이 bridge를 감싸는 adapter 후보로 두었다. 다만 현재 bridge의 persona/session state는 Manager app 소유이며 중앙 canonical project state가 아니다.

### MCP와 host ingress

- `src/mcp-http.mjs`: JSON schema 검증, MCP dispatcher, auth, protocol handling.
- `vendor/h-plugin/contracts/mcp-tool-surface.json`: Eve의 고정 7-tool 계약.
- `src/host-context.mjs`: invocation context validation과 deterministic run key.
- `src/host-invocation-store.mjs`: durable idempotency ledger.
- `src/notion-chat-relay.mjs`: 기존 Notion request/response relay.
- `src/desktop-webmcp-bridge.mjs`: ChatGPT desktop용 local bridge.

판정: Eve MCP의 7-tool surface는 변경하지 않는다. 중앙 adapter가 기존 endpoint를 소비한다. 일반 Control Plane MCP registry와 Eve의 frozen contract는 별도 책임으로 유지한다.

### 상태·관측·provenance 패턴

- `src/observability.mjs`: correlation context와 runtime metrics.
- `src/provenance-graph.mjs`: typed provenance node/edge 모델.
- `src/runtime-error-classification.mjs`: 오류 분류.
- `src/drift-detector.mjs`: Notion/PostgreSQL drift 검사 패턴.
- `src/release-rollback-automation.mjs`: release/rollback 패턴.
- `src/production-migrate.mjs`: PostgreSQL migration 진입점.

판정: 아이디어와 계약 패턴은 참고하되 파일을 복사해 새로운 중복 구현으로 만들지 않는다. All Tomorrow의 trace/event 계약이 확정된 후 adapter가 Eve correlation/provenance identifier를 보존하도록 한다.

## 이미 계획과 겹치는 부분

| 계획 개념 | 기존 구현 | 상태 |
|---|---|---|
| Discord edge | 기존 bot, ACL, cache, retrieval budget | 상당 부분 존재. central escalation 판단은 아직 별도 계약이 필요하다. |
| Worker adapter | Antigravity Manager bridge | 특정 worker에 한해 존재. 범용 registry는 없음. |
| MCP adapter | Eve HTTP MCP, Discord stdio MCP | 개별 구현은 존재. 중앙 Tool Registry는 없음. |
| Trace/correlation | RuntimeObservability correlation context | Eve runtime 내부에는 존재. cross-system trace 계약은 없음. |
| Discord/Manager audit | 원격 최신 main의 JSONL audit event와 `audit_id` 전파 | 중앙 trace adapter seam으로 재사용 가능. 중앙 event store 자체를 대체하지는 않음. |
| Provenance | ProvenanceGraph | Eve 도메인 구현은 존재. 중앙 event history와 연결 필요. |
| Durable idempotency | host invocation ledger | Eve ingress에는 존재. 범용 pipeline run resume에는 없음. |
| Scheduler | Eve autonomous scheduler | Eve 전용. 중앙 background scheduler로 재분류하지 않는다. |
| Canonical state ownership | Notion + PostgreSQL의 기존 경계 | 유지해야 함. 중앙 migration 금지. |

## 확인되지 않은 시스템

다음은 로컬 실물이나 신뢰할 수 있는 계약을 아직 찾지 못했다.

- OpenCode를 worker로 호출하는 중앙용 endpoint/contract
- Codex worker adapter
- Sol Pi integration
- 별도 Manager runtime 저장소가 존재하는지 여부
- Antigravity 외부 호출의 장기 지원 contract
- 사용 가능한 AWS 예산, domain, authentication provider
- Notion의 Manager/Eve source ownership 전체 지도

이 항목은 현재 completion-stage 작업에서 실제로 필요해질 때 다시 검증하고, 필요한 정보가 없으면 사용자에게 좁게 질문한다. 지금 가짜 integration이나 placeholder network client를 만들지 않는다.

## 재사용 우선순위

1. 기존 Discord Gateway와 `DiscordService`를 유지한다.
2. Eve는 frozen MCP/host ingress를 통해 호출한다.
3. Antigravity는 기존 Manager bridge의 공개 가능한 경계를 adapter로 감싼다.
4. 기존 correlation/idempotency 개념을 cross-system contract 설계에 반영한다.
5. Notion 정본은 이동하지 않고 Memory Gateway의 source-owned adapter로 접근한다.

## 금지할 복제

- All Tomorrow 안에 두 번째 Eve state store 생성
- Discord 전용 project/task 정본 생성
- Manager persona/session state를 중앙 user/project state로 오인
- 기존 Eve 7-tool MCP를 중앙 편의를 위해 변경
- handover 문서를 event store 대신 history 원본으로 사용
