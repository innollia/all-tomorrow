# Stage 1 Implementation Map

Stage 1 각 packet의 예정 코드/migration/test 위치. **실제 구현은 Stage 0 완료 후** 시작한다.

## 01 Durable Kernel

| Packet | 예정 구현 | Migration | 예정 테스트 |
|---|---|---|---|
| 01A | domain/storage schema models | Goal/Work/Run/Outcome/Event/Delivery/Question linkage migration | migration + live PostgreSQL |
| 01B | `src/all_tomorrow/domain/`, `src/all_tomorrow/storage/` 기존 구조 확장 | 필요 시 revision/index | domain/store concurrency |
| 01C | `src/all_tomorrow/ports/durable.py`, selected adapter | delivery/reconciliation state 필요 시 | duplicate start/process kill |
| 01D | execution service + PipelineRuntime compatibility + Question linkage | Question schema 확장 | linkage/NEED_USER restart |
| 01E | 제품 코드 없음, acceptance fixtures 중심 | 없음 | live DB/backend L1/L2 suite |

## 02 Researcher Loop

| Packet | 예정 구현 | Migration | 예정 테스트 |
|---|---|---|---|
| 02A | `src/all_tomorrow/researcher/observation.py` | observer_cursors | cursor/concurrent wake |
| 02B | `src/all_tomorrow/researcher/agent.py`, decision models | 없음 | typed decision/schema |
| 02C | `src/all_tomorrow/researcher/materialize.py` | materialization idempotency index | atomic/idempotent mutation |
| 02D | `src/all_tomorrow/researcher/budget.py`, dedup policy | lineage/fingerprint/budget ledger | race/budget |
| 02E | 없음 | 없음 | researcher acceptance |

## 03 Evaluation & Self-Improvement

| Packet | 예정 구현 | Migration | 예정 테스트 |
|---|---|---|---|
| 03A | `src/all_tomorrow/improvement/store.py`, models | proposals/criteria/evaluation/user_feedback | lifecycle/immutability |
| 03B | `src/all_tomorrow/improvement/evaluator.py` | 없음 | hard policy/tamper |
| 03C | `src/all_tomorrow/improvement/sandbox.py`, target adapters | 없음 | isolation/reproducibility |
| 03D | `src/all_tomorrow/improvement/promotion.py`, deployment adapters | deployment refs 필요 시 | apply/monitor/rollback |
| 03E | `src/all_tomorrow/improvement/protection.py` | approval handoff metadata | fail-closed classification |
| 03F | 없음 | 없음 | self-improvement acceptance |

## 04 Runtime & Tools

| Packet | 예정 구현 | Migration | 예정 테스트 |
|---|---|---|---|
| 04A | model route/PydanticAI wiring + LiteLLM config | usage refs 필요 시 | gateway/retry/privacy |
| 04B | existing worker adapter에 Codex adapter | 없음 | parser/sandbox/secret |
| 04C | workspace resolver/binding | workspace binding가 DB라면 명시 migration | realpath/dirty/source |
| 04D | deployment/IaC/service configs | 없음 | AWS reboot/restore/deploy |
| 04E | laptop approval service/store | approval/nonce/audit | threat-model L3 |
| 04F | artifact store adapter/metadata | artifact metadata/GC refs | integrity/GC/access |
| 04G | secret/ops/security configuration | alert/audit metadata 필요 시 | rotation/alert/dependency security |

## 05 Report & Priority

| Packet | 예정 구현 | Migration | 예정 테스트 |
|---|---|---|---|
| 05A | report store/projection | reports/revisions | idempotency/late Event |
| 05B | report composer | 없음 | source-backed/fallback |
| 05C | priority policy | policy ref 저장 필요 시 | dispatch/yield/starvation |
| 05D | report trigger/access | trigger/report fields | timezone/DST/auth |
| 05E | 없음 | 없음 | integrated acceptance |

## 06 Acceptance

- 06A: `tests/acceptance/fixtures/`
- 06B: `tests/acceptance/test_stage1_end_to_end.py` 또는 repo convention에 맞춘 동등 위치
- 06C: stage close evidence/docs only

## 구현 순서 공통

migration → domain/types → store → service/policy → adapter → L0/L1 tests → L2 process tests → 필요한 L3 deployed acceptance 순서.

새 파일명은 실제 repo에 동일 책임 module이 없을 때만 사용한다. 기존 module을 무시하고 병렬 framework를 만들지 않는다.
