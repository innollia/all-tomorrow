# 00C — Failure Walking Skeleton

## Status

- 상태: **개발중**
- 선행조건: 00A + 00B
- 공통 계약:
  - ../plan-verification-contract.md
  - ../domain-contracts.md
  - ../failure-recovery-contract.md
  - ../data-security-artifact-contract.md

## 목적

가장 위험한 failure boundary를 실제 process/PostgreSQL/substrate로 한 번 끝까지 관통해 00B contract가 구현 가능한지 증명한다.

## Skeleton

user request
→ Goal/Work
→ Run STARTING commit
→ durable execution start + ExecutionRef attach
→ PydanticAI agent
→ worker/tool call
→ durable NEED_USER wait
→ Question projection
→ user signal
→ resume
→ ArtifactRef/result 기록
→ Run/Work completion

mock-only skeleton은 완료 증거가 아니다.

## Test topology

L2 scenario는 최소 다음 process를 독립 종료 가능하게 구성한다.

- All Tomorrow application worker/process
- selected durable backend runtime/state service
- LiteLLM Proxy
- tool/worker fixture process
- PostgreSQL

failure barrier는 parent test가 IPC/file/socket/event 등으로 관측 가능한 신호를 받아 정확한 지점에서 child process를 kill한다.

동일 process의 exception injection은 unit 보조 테스트일 뿐 L2 evidence가 아니다.

## External mutation fixture

fixture는 최소 다음을 durable하게 기록한다.

- idempotency_key
- invocation_count
- applied_effect_count
- committed effect value/hash
- first/last request ids

통과 기준은 mutation class별 semantics를 따른다.

- replay-safe mutation: invocation_count는 2 이상일 수 있으나 applied_effect_count=1
- reconcile-before-retry: ambiguous recovery 중 effect 조회 후 불필요한 재적용 없음
- non-retryable ambiguous: 자동 두 번째 effect 금지

## Failure scenarios

| ID | 주입 위치 | 필수 관측 | 통과 조건 | Level |
|---|---|---|---|---|
| C-01 | model 호출 직전 app process kill | same work_id/run_id/execution | 새 Run 없이 resume | L2 |
| C-02 | external effect commit 직후 app process kill | invocation/applied count | 허용 semantics 이상 중복 없음 | L2 |
| C-03 | NEED_USER wait 중 app restart | Question + durable wait | 질문 중복 생성 없이 같은 signal로 resume | L2 |
| C-04 | Run commit 직후 external start 전 kill | STARTING/no-ref | same run_id reconciliation로 execution 1개 | L2 |
| C-05 | external start 직후 ref attach 전 kill | backend execution + no local ref | 기존 execution 회수, 새 execution 없음 | L2 |
| C-06 | same run_id concurrent start 2회 | backend execution count | logical execution 1개 | L1/L2 |
| C-07 | worker timeout | Run/Work state + process cleanup | timeout evidence 보존, Goal 자동 유실 없음 | L1 |
| C-08 | V1 in-flight 후 V2 배포 | persisted history | direct replay 또는 00E에서 선택할 drain strategy가 실제 동작 | L2 |
| C-09 | concurrent reconciler 2개 | Run revision/ref | 동일 ref 수렴 또는 fail-closed, divergent attach 금지 | L1 |
| C-10 | tool/backend unavailable | UNKNOWN/failed evidence | 성공/empty로 위조하지 않음 | L1 |

각 scenario는 wrong-implementation fixture 또는 negative assertion을 둔다.

## Identity/provenance assertions

모든 scenario에서 확인:

- Goal identity 유지
- Work identity 유지
- 같은 logical attempt면 run_id 유지
- ExecutionRef가 Run에 연결
- question/signal idempotency
- tool/worker request provenance
- ArtifactRef content hash
- trace correlation
- terminal/unknown state가 실제 관측과 일치

## Database boundary

한 PostgreSQL server를 써도 되지만 logical ownership은 분리한다.

- All Tomorrow application/domain DB/schema
- durable backend system DB/schema

All Tomorrow migration은 backend 내부 table을 생성/수정하지 않는다.

## Data-retention probe

식별 가능한 canary를 다음에 서로 다른 값으로 넣는다.

- prompt
- tool input
- tool output
- secret-like fixture
- artifact payload

완료 후 inventory:

- application DB
- durable backend journal/state
- LiteLLM logs/spend logs
- OTel exporter
- stdout/stderr
- artifact store

각 surface에 expected present/absent와 retention class를 기록한다.
"안 남아야 하는 곳"에서 발견되면 실패다.

## Artifact probe

large/raw document는 durable step output에 직접 넣지 않는다.

검증:

1. artifact storage에 immutable content 저장
2. ArtifactRef/hash만 semantic state 및 execution payload에 전달
3. fetch 시 hash 검증
4. oversized raw content가 journal/Event/telemetry에 복제되지 않았음을 확인

## 완료조건

C-01~C-10과 retention/artifact probe가 요구 level에서 통과하고, 실패 evidence가 저장된 상태로 재현 가능해야 한다.
