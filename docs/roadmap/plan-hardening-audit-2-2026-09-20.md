# Second-pass Plan Hardening Audit — 2026-09-20

범위: 첫 hardening 이후 다시 발견한 50개 부족점.

상태 의미:

- **DESIGN_CLOSED**: 계획/계약/packet 수준에서 해결. 실제 구현 완료를 뜻하지 않음.
- **PLANNED_IMPLEMENTATION**: 구현할 파일·검증 위치까지 계획됐으나 실제 코드는 Stage gate 이후 작업.
- **EVIDENCE_BLOCKED**: Stage 0 실험/실배치 evidence 없이는 값을 확정하면 안 됨.
- **REVIEW_REQUIRED**: 현재 main branch 상태를 추가 확인해야 함.

| # | 문제 | 상태 | 계획상 처리 |
|---:|---|---|---|
| 1 | 00B 과대 packet | DESIGN_CLOSED | 00B-1~6 실제 파일 분할 |
| 2 | Stage 2 macro 과대 | DESIGN_CLOSED | 2.1A~E, 2.2A~D, 2.3A~D, 2.4A~D 분할 |
| 3 | Stage 3 macro 과대 | DESIGN_CLOSED | 3.1A~D, 3.2A~E, 3.3A~D, 3.4A~E 분할 |
| 4 | 코드 위치 부족 | DESIGN_CLOSED | Stage0/1 implementation-map + Stage2/3 packet별 예정 경로 |
| 5 | packet 구현 순서 부족 | DESIGN_CLOSED | migration→domain→store→service→adapter→L0/L1→L2→L3 순서 |
| 6 | verification contract 강제 장치 없음 | PLANNED_IMPLEMENTATION | manifest + roadmap-automation-contract; linter/CI는 향후 구현, 이번 작업에서 코드 생성 안 함 |
| 7 | audit가 과하게 처리 완료 선언 | DESIGN_CLOSED | 본 문서에서 설계/구현/evidence 상태 분리 |
| 8 | Goal state machine 없음 | DESIGN_CLOSED | control-plane-contracts |
| 9 | Run success→Work success 관계 없음 | DESIGN_CLOSED | CompletionEvidence evaluator 필요 |
| 10 | active Run 동시성 미정 | DESIGN_CLOSED | 기본 Work당 active Run 1개; speculative는 별도 policy |
| 11 | Work→Goal completion propagation 없음 | DESIGN_CLOSED | Goal completion_policy + Outcome |
| 12 | Outcome/CompletionEvidence 없음 | DESIGN_CLOSED | canonical OutcomeRecord |
| 13 | Event contract 없음 | DESIGN_CLOSED | EventRecord schema/ordering/idempotency/append-only 의미 |
| 14 | error taxonomy 없음 | DESIGN_CLOSED | CanonicalError categories |
| 15 | Run start 외 dual-write seam 부족 | DESIGN_CLOSED | delivery-consistency-contract |
| 16 | Outbox/Inbox protocol 없음 | DESIGN_CLOSED | DeliveryRecord + inbound dedup |
| 17 | SourceRef 없음 | DESIGN_CLOSED | SourceRef canonical schema |
| 18 | Project contract 없음 | DESIGN_CLOSED | ProjectRecord + owner/source scope |
| 19 | Tool contract 부족 | DESIGN_CLOSED | ToolDescriptor |
| 20 | Worker contract 부족 | DESIGN_CLOSED | WorkerDescriptor |
| 21 | 일반 external action authorization 없음 | DESIGN_CLOSED | ALLOW/CONFIRM/DENY ActionAuthorization |
| 22 | user/project 역할 모델 없음 | DESIGN_CLOSED | owner/editor/viewer 최소 role |
| 23 | Artifact bytes storage 미정 | EVIDENCE_BLOCKED | 04F packet; 00E/04D에서 filesystem/S3 등 실제 backend 선택 |
| 24 | secret management backend 미정 | EVIDENCE_BLOCKED | 04G/operations contract; AWS topology 뒤 backend 확정 |
| 25 | ContextPack prompt-injection 경계 부족 | DESIGN_CLOSED | untrusted content/control authority 분리 |
| 26 | prompt/policy version store 모호 | DESIGN_CLOSED | immutable prompt/policy version/hash contract |
| 27 | Usage/Cost canonical model 없음 | DESIGN_CLOSED | UsageRecord + actual/estimated + price-table ref |
| 28 | deadline/time semantics 부족 | DESIGN_CLOSED | absolute deadline/local calendar/monotonic timeout 분리 |
| 29 | P0~P6 의미 미정 | DESIGN_CLOSED | 05C에서 P0~P6, aging/starvation 확정 |
| 30 | 일반 Work replan 폭주 제한 없음 | DESIGN_CLOSED | 00B-4 replan budget/same-error suppression |
| 31 | Question supersession 없음 | DESIGN_CLOSED | SUPERSEDED 상태 + late-answer 규칙 |
| 32 | Goal cancellation semantics 없음 | DESIGN_CLOSED | child Work/Run/Question/Trigger cooperative propagation |
| 33 | DB migration mixed-version 전략 부족 | DESIGN_CLOSED | expand/contract + irreversible protected rule |
| 34 | API schema/versioning 없음 | DESIGN_CLOSED | operations contract + 2.1B/2.2B |
| 35 | idempotency key retention/GC 없음 | DESIGN_CLOSED | namespace/version/scope/validity window |
| 36 | repair/operator workflow 없음 | DESIGN_CLOSED | 2.3D Repair packet |
| 37 | dead-letter terminal recovery state 없음 | DESIGN_CLOSED | REPAIR_REQUIRED |
| 38 | audit tamper resistance 없음 | DESIGN_CLOSED | append-only ordinary path + privileged maintenance |
| 39 | alerting/SLO 없음 | DESIGN_CLOSED | 04G에 최소 operational alert set |
| 40 | CI exact 파일/명령 부족 | PLANNED_IMPLEMENTATION | roadmap automation/00D에 예정 위치와 gate 정의; 실제 workflow 코드는 이번 범위 밖 |
| 41 | roadmap dependency machine-readable 아님 | DESIGN_CLOSED | manifest.json |
| 42 | 상태표 자동 sync 없음 | PLANNED_IMPLEMENTATION | linter 계획만 작성, 실제 script/Actions는 미구현 |
| 43 | 00A 상태와 실제 work 동기화 의심 | REVIEW_REQUIRED | main에서 별도 spike 구현 흔적을 식별하지 못해 현재 상태 유지; 구현 재개 전 evidence audit 필수 |
| 44 | Stage3 BLOCKED state 미결정 | DESIGN_CLOSED | 1차는 Work WAITING + wait_reason=dependency_blocked |
| 45 | proactive brief delivery path 없음 | DESIGN_CLOSED | 2.2D OutboundDelivery + 3.1C |
| 46 | outbound message contract 없음 | DESIGN_CLOSED | OutboundDelivery |
| 47 | compensation 없음 | DESIGN_CLOSED | optional CompensationSpec |
| 48 | dependency security 부족 | DESIGN_CLOSED | 04G: vulnerability/SBOM/license/digest/update provenance 계획 |
| 49 | requirement naming 제각각 | PLANNED_IMPLEMENTATION | global S{stage}-{packet}-{NN}; Stage1 legacy prefix는 manifest target_requirement_prefix로 migration |
| 50 | 기존 packet이 공통 14개 section을 모두 직접 포함하지 않음 | DESIGN_CLOSED_WITH_MAP | 공통 contract + Stage0/1 implementation-map + Stage2/3 subpacket 분할. 구현 직전 packet은 missing section을 보완해야 시작 가능 |

## 현재 evidence-dependent blockers

실험/실배치 전에는 숫자나 제품을 추측해서 채우지 않는다.

1. selected durable backend/version
2. run_id→backend identity mapping
3. 실제 retry owner/attempt/timeout/backoff 값
4. backend priority/delay/signal/cancel mapping
5. V1→V2 replay vs drain
6. MCP gateway 선택
7. PipelineRuntime disposition
8. AWS exact process topology
9. Artifact bytes backend
10. ordinary AWS secret backend
11. journal/gateway/artifact retention 기간
12. remote-control RPO/RTO
13. actual alert threshold/window

## 계획 범위 경계

이번 hardening 작업은 **계획서만 수정**한다.

다음은 계획되어 있지만 아직 구현하지 않는다:

- roadmap linter Python script
- roadmap lint tests
- GitHub Actions workflow
- Stage 1~3 product code
- migrations
- deployment configuration

실제 구현은 각 packet의 prerequisite와 evidence blocker가 해소된 뒤 시작한다.
