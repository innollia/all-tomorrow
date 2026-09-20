# Plan Hardening Audit — 2026-09-20

범위: 00B 이후 roadmap 전체.

목적: 계획의 추상성 때문에 구현자가 이름만 맞춘 형식적 구현으로 빠지는 문제를 막고, 최초 감사에서 지적한 항목이 어떤 contract/packet으로 닫혔는지 추적한다.

## 공통 기반

- plan-verification-contract.md: requirement→verification→evidence, evidence level, negative test, completion gate, upstream invalidation
- domain-contracts.md: Goal/Work/Run/ExecutionRef/Request/Question/Artifact/Trigger/Resource identity와 state semantics
- failure-recovery-contract.md: retry owner, mutation semantics, cross-store reconciliation, real crash, upgrade, trigger/time
- data-security-artifact-contract.md: data class/retention, artifact integrity, fail-closed protection, approval threat model, supply-chain

## 최초 문제 54개 처리표

| # | 문제 | 처리 |
|---:|---|---|
| 1 | 완료조건이 실행 가능한 acceptance가 아님 | 공통 verification contract로 필수 형식화 |
| 2 | 요구→테스트→증거 추적성 없음 | requirement traceability/evidence level 추가 |
| 3 | Work/Run/ExecutionRef 충돌 | ExecutionRef를 Run 소유로 통일, 01A~01E rewrite |
| 4 | DurableExecutionPort semantic 부족 | 00B에 start/get/cancel/signal/result 정상/오류/idempotency contract |
| 5 | reconciliation 알고리즘 부족 | failure-recovery + 00B/01C에 CAS/concurrent reconciler/exhaustion |
| 6 | retry owner 미결정 | 00B completion blocker로 명시, 00A evidence 후 필수 확정 |
| 7 | LiteLLM/PydanticAI/MCP ownership 중첩 | 00B ownership matrix 재작성 |
| 8 | failure injection 불명확 | 실제 child process barrier/kill을 L2 조건으로 고정 |
| 9 | side-effect fixture 불명확 | invocation_count/applied_effect_count + 3 mutation semantics |
| 10 | version upgrade recovery 불명확 | V1→V2 replay/drain contract, 00E strategy lock |
| 11 | eval acceptance 추상적 | 00D E-01~E-08 hard cases/규칙 |
| 12 | CI 환경/gate 불명확 | 00D CI lanes + required environment/evidence |
| 13 | Architecture Lock 산출물 불명확 | 00E ADR 형식/필수 결정/Stage1 rewrite gate |
| 14 | canonical state machine 없음 | domain-contracts Work/Run/Question semantics |
| 15 | dedup concurrency unsafe | 02D DB unique/transaction-safe dedup |
| 16 | fingerprint 불안정 | 02D versioned canonical fingerprint |
| 17 | budget accounting semantics 없음 | 02D reserve/consume/refund/unknown/concurrency |
| 18 | clear improvement/regression 기준 없음 | 03B hard policy |
| 19 | candidate가 평가 기준 조작 가능 | 03A criteria freeze + 03B/03C tamper rejection |
| 20 | auto promotion deployment 너무 추상적 | 03D target별 deployment plan/code deploy/in-flight strategy |
| 21 | protected unknown fail-closed 아님 | data-security + 03E unknown=protected |
| 22 | Approval threat model 부족 | 04E attack scenarios/nonce/expiry/hash/session/CSRF |
| 23 | AWS runtime deployment plan 부족 | 04D topology/network/supervisor/secret/backup/rollback |
| 24 | ASK_USER storage 미결정 | 01D canonical Question contract, 02C에서 확정 사용 |
| 25 | decision payload validation 부족 | 02B discriminated typed union |
| 26 | autonomous Goal acceptance 주관적 | 02E evidence/outcome criterion + terminal investigation |
| 27 | monitoring window 미정 | 03D explicit versioned monitoring policy 없으면 auto-promote 불가 |
| 28 | workspace security boundary 부족 | 04C realpath/root/dirty/source identity |
| 29 | report identity/versioning 미정 | 05A logical period/input watermark/revision |
| 30 | report time semantics 부족 | 05D timezone/DST/misfire/catch-up |
| 31 | priority yield가 backend ownership과 충돌 | 05C semantic priority와 selected-backend preemption 분리 |
| 32 | Stage1 상태표 모순 | 04 parent/children 전부 Stage0 gate에 맞춤 |
| 33 | 용어 비정규화 | domain-contracts glossary, pipeline execution 별도 ref |
| 34 | 01C 파일명이 durable queue | durable-execution-bridge로 rename |
| 35 | Stage1 acceptance 환경별 level 없음 | 06 L0~L3 matrix |
| 36 | privacy/retention lifecycle 부족 | data-security retention lifecycle |
| 37 | artifact contract 없음 | domain + data-security ArtifactRef |
| 38 | Stage2 전체 지나치게 추상적 | Stage2 1~5 전면 rewrite |
| 39 | ingress contract 없음 | 2.1 Request/Delivery/idempotency |
| 40 | remote-control 보안 부족 | 2.2 auth/session/CSRF/isolation |
| 41 | backup/restore 완료조건 없음 | 2.2 RPO/RTO/restore/reconciliation |
| 42 | bounded ContextPack 없음 | 2.3 contract/selection/conflict/budget |
| 43 | cancel/replan semantics 없음 | domain + 2.3 |
| 44 | routing policy 미설계 | 2.4 hard filter→rank→failure/fallback |
| 45 | Stage3가 vision 수준 | Stage3 1~5 전면 rewrite |
| 46 | personal/school owner adapter 없음 | 3.1 Owner Adapter/source precedence |
| 47 | trigger semantics 없음 | 3.2 TriggerRecord/fire/misfire/webhook/watcher |
| 48 | knowledge loop acceptance 약함 | 3.2 Lesson lifecycle/reuse outcome |
| 49 | discovery supply-chain 보안 없음 | data-security + 3.3 sandbox/provenance |
| 50 | Resource Pool accounting 없음 | 3.3 reservation/capacity/actual usage |
| 51 | long-horizon graph 의미 없음 | 3.4 dynamic DAG/dependency/replan |
| 52 | 실제 진전 측정 없음 | 3.4 milestone Artifact/test evidence |
| 53 | downstream stale plan 감지 없음 | verification contract upstream invalidation |
| 54 | 공통 계획서 형식 없음 | verification contract packet 최소 형식 |

## 의도적으로 남긴 evidence-dependent blockers

다음은 계획 누락이 아니라 00A/00E 또는 실제 deployment 결과 없이 지금 값을 고르면 추측이 되므로 blocker로 남긴다.

1. selected durable backend와 exact version
2. run_id → selected backend identity mapping
3. provider/model/tool retry primary owner의 실제 선택과 attempts/timeout/backoff 수치
4. selected backend priority/delay/signal/cancel mapping
5. V1→V2 direct replay vs blue-green/drain의 실제 선택
6. LiteLLM MCP Gateway vs FastMCP fallback 결과
7. PipelineRuntime disposition
8. AWS exact process topology/version
9. journal/gateway/artifact 실제 retention 기간
10. Remote-control RPO/RTO 숫자
11. Stage 3 dependency wait를 Work WAITING+reason으로 유지할지 별도 BLOCKED state를 추가할지

이 값은 해당 선행 evidence가 생긴 즉시 00E/해당 packet에서 확정해야 하며, 미정 상태로 downstream packet을 개발완료 처리할 수 없다.

## 감사 결론

00B 이후 roadmap은 이제 공통 identity/failure/security/verification contract를 공유한다. 남은 미정값은 구현자의 임의 해석 영역이 아니라 명시적 선행조건/완료 blocker로 분리되어 있다.
