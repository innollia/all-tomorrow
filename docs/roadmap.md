# All Tomorrow Roadmap

이 파일은 master status index다. 세부 구현 계획을 여기에서 읽지 않는다.

## Current Position

| Stage | 상태 | 지금 시작 가능 | 선행조건 | 상세 |
|---|---|---:|---|---|
| 0. OSS Assembly & Architecture Proof | 개발완료 | 예 | 없음 | [status/index](roadmap/stage-00-assembly/index.md) |
| 1. Durable Self-Improving Researcher | 개발중 | 예 | Stage 0 완료 | [status/index](roadmap/stage-01-researcher/index.md) |
| 2. Reliable Assistant & Remote Control | 선행작업 대기 | 아니오 | Stage 1 완료 | [status/index](roadmap/stage-02-assistant/index.md) |
| 3. Personal Manager & Generalized Autonomy | 선행작업 대기 | 아니오 | Stage 2 완료 | [status/index](roadmap/stage-03-manager/index.md) |

## 지금 바로 작업 가능한 것

- 2026-10-22 관제 브리핑 강화: **개발완료**(중앙 구현·회귀시험·실제 노션 브리핑). Discord 멱등 수신·무료 모델 증분 요약·매시간/수동 브리핑을 연결했다. 관련 18 passed, 전체 781 passed / 69 skipped / 기존 외부 OpenCode smoke 1 failed. 실제 Discord 송신 연결은 미확인이다. [검증·실행 기록](control-brief.md).

- 2026-10-22 메타인지 Antigravity 판단 전환: **개발완료**(코드·가짜 실행기 회귀시험). 기본 Antigravity, 깨어남별 Codex 대체와 모델·실패 사유 기록을 연결했다. 이 환경에는 agy CLI가 없어 실제 Gemini 응답은 미확인이다. Stage 1은 개발중을 유지한다. [진행 기록](dp7-loop.md).

- 2026-10-22 Claude 로그인 오보·파일 보고 답장 보정: **개발완료**(코드·회귀시험). 명시적 User-Agent, 인증 만료와 통신 오류 분리, 파일 답장 보존·메타인지 전달을 구현했다. 실계정·Discord 운영 확인은 별도이며 Stage 1은 개발중을 유지한다. [진행 기록](overseer-plan.md).

Stage 0는 [종료 검증 기록](roadmap/stage-00-assembly/00-close-live-verification.md)에 따라 개발완료다. 지금은 **Stage 1의 메타인지 → Work → 작업자 → 시험 → 반영/되돌림 → 디스코드 보고 고리**를 DP7에서 연결한다. 부품 테스트 통과를 Stage 전체의 운영 완료로 보지 않는다.

- 현재: [DP7 자기개선 고리](dp7-loop.md)의 코드·InMemory 검증과 Eve 양방향 창구 연결, 실제 DB/Discord/재부팅 검증 준비
- 2026-10-21 Work 실패·무변경 깨어남 보정: **개발중**. 작업자 진단·fallback, 무변경 검사, Interactive 등록/재기동 수정. 관련 64 passed, 전체 747 passed / 69 skipped / 기존 OpenCode smoke 1 failed. 관제 재등록·실제 Work 성공 검증은 남았다. [근거와 명령](dp7-loop.md#2026-10-21-work-실패무변경-깨어남-보정).
- 다음: 사용자가 넣은 비밀값으로 관제가 예약 작업을 등록하고 자발적인 수정 보고를 확인

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

## 승인된 로컬 worker 연결

2026-09-27 사용자 요청으로 OpenCode·Codex·Kiro·Antigravity를 기존 WorkerService에 연결하는 작업을 먼저 수행한다. Stage 0 gate의 예외는 이 로컬 CLI 연결과 직접 검증으로 한정한다. 00D/00E 및 Stage 1의 기존 완료조건과 상태는 유지한다.

| 작업 | 상태 | 기록 |
|---|---|---|
| 네 로컬 worker 연결 | 개발완료 | [실행 방법과 검증 기록](worker-adapters.md) |

## 콘솔 기능 이식

2026-10-19 사용자 요청으로 만든 콘솔 기능을 main으로 옮기는 중이다. 처음 구현은 main의 Stage 1–3·device agent 이전에 갈라진 `feat/stage-00d-close`에서 했고, `feat/port-console-features`로 이식한다(2026-10-19). Stage 표의 상태와는 별개다.

| 작업 | 상태 | 기록 |
|---|---|---|
| 구독 사용량 패널 | 개발중 | [구조와 남은 일](usage-panel.md) |
| Claude→All Tomorrow MCP 연결 | 개발중 | [구조·검증·남은 일](mcp-control.md) |
| 사업 아이디어 공장 + 통제 콘솔 | 개발중 | [계획서·검증 기록](idea-factory-plan.md) |
| 중앙 콘솔 프로젝트 패널 | 개발중 | [구조·결정·보안 사항](project-panels.md) |

## 교차 세션 관제

2026-10-20 사용자 요청이다. 다섯 도구(Claude Code·Codex·OpenCode·Kiro·Antigravity)의 세션 기록을 모아 문제·해결 카드로 정리한다. 다른 곳에서 해결된 문제는 막힌 세션에 건넨다. 사용자는 계속 개별 세션에 직접 일을 시킨다. Stage 표의 상태와는 별개다.

| 작업 | 상태 | 기록 |
|---|---|---|
| 교차 세션 관제 | 개발중 | [계획서·진행 기록](overseer-plan.md) |

## 2026-10-21 DP7 Windows Selector 수정

이벤트 루프 수정 상태: **개발완료**. Stage 1 전체는 **개발중**을 유지한다. API·executor·overseer 및 수동 metacog는 Windows Selector를 사용하고, 작업자 subprocess는 별도 스레드 Proactor에서 실행한다. collect --no-metacog는 PostgreSQL을 사용하지 않는다.

검증: 관련 **26 passed**, 전체 **728 passed, 69 skipped, 1 failed**. 실패는 기존 외부 npx/OpenCode help 실행이다. 실제 DB SELECT 1과 임시 API /healthz HTTP 200을 확인했다. 기존 5476 예약 작업은 재시작하지 않았다. 상세 기록은 docs/dp7-loop.md에 있다.
