# 1차 완성 — Durable Self-Improving Researcher

> Status: **In progress.** 첫 번째 사용자 체감 제품은 "스스로 공부하고 자기 자신을 개선하는 연구원"이다. 그 연구원을 지탱하는 최소 durable kernel을 먼저 닫고, 곧바로 실제 researcher loop를 올린다.

## Definition of Done

1차가 끝나면 All Tomorrow는 단순 pipeline runner가 아니다.

항상 켜진 중앙 상태를 바탕으로 스스로 관찰·조사·실험하고, 필요하면 새로운 Goal을 만들며, 자신의 prompt/policy/code까지 개선 후보로 삼아 평가하고, 허용된 변경은 스스로 production에 적용한 뒤 사용자에게 보고할 수 있어야 한다.

다만 권한·비용·통제 경계를 넓히는 변경은 노트북의 별도 Approval Authority 없이 production에 적용할 수 없어야 한다.

1차의 첫 구현물은 durable kernel이지만, **첫 완성품은 researcher**다.

## Product Order vs Implementation Dependency

제품 우선순위:

1. Researcher
2. Reliable assistant
3. Personal manager

구현 의존성:

1. minimal durable kernel
2. researcher loop
3. self-evaluation / self-improvement
4. always-on deployment and reporting

"연구원이 먼저"라는 요구를 이유로 persistence와 rollback을 생략하지 않는다. 반대로 durable core를 이유로 Web/Discord/Eve/Manager 같은 주변 기능을 1차에 전부 넣지도 않는다.

## 0. Preserve Existing Good Work

유지·확장:

- RequestEnvelope / ExecutionContext / NodeResult
- immutable PipelineSpec version
- NEED_USER + resume
- append-only Event / trace
- source-owner-aware adapter boundary
- CapabilityRegistry / WorkerService
- Antigravity / OpenCode worker adapters
- Discord local-vs-central edge policy
- lesson/evaluation/scheduler 초기 골격
- credential 값을 중앙 장기 기록에서 배제하는 원칙

현재 구조를 전부 갈아엎지 않고 researcher에 필요한 최소 책임만 위에 올린다.

## Gate A — Minimal Durable Kernel

먼저 단일 기기 개발 환경에서 다음을 닫는다.

### Goal / Work / Run

- Goal: 여러 Work와 시간대를 넘어 유지되는 목적
- WorkItem: durable 실행 단위
- Run: WorkItem의 한 실행 시도

Run 실패가 곧 Goal 실패가 되지 않는다.

현재 tasks를 폐기부터 하지 않는다. 확장 가능한지 먼저 검토하고, 실제로 부족한 persistence만 migration한다.

### State + Event

현재 상태 projection은 PostgreSQL row에 둔다.

Event는 provenance와 관찰 기록으로 append-only 유지한다.

상태 변경과 관련 Event append는 같은 transaction boundary에서 정합성을 보장한다. 전체 현재 상태를 Event replay만으로 복원하는 완전 event-sourcing은 요구하지 않는다.

### Minimal state model

상태 enum을 문제 종류별로 비대하게 늘리지 않는다.

예:

- Work: PENDING / RUNNING / WAITING / SUCCEEDED / FAILED / CANCELLED
- Goal: ACTIVE / PAUSED / COMPLETED / CANCELLED
- 세부 대기 이유는 wait_reason 또는 metadata로 표현

### Crash and resume

- process restart 뒤 Goal/Work/Run 조회
- NEED_USER restart-safe resume
- concurrent resume 방지
- retry/requeue
- cancellation
- provenance retention

## Gate B — Researcher Loop

durable state가 닫히면 곧바로 researcher를 실제로 움직인다.

Researcher는 Work layer와 병렬로 다음을 관찰할 수 있다.

- Goal / Work / Run / Event / Artifact
- 자신의 이전 관찰과 판단
- 자신이 생성한 Goal/Work
- prompt / policy / model 선택
- 비용과 지연
- evaluation 결과
- 사용자의 평가와 실제 사용 결과

특정 문제 taxonomy를 먼저 주지 않는다.

관찰 결과 필요하면:

- 조사 Work 생성
- 실험 Work 생성
- 기존 Work 변경
- 새로운 Goal 자체 생성
- improvement proposal 생성
- 필요한 사용자 질문 생성

을 할 수 있다.

별도의 meta-meta-meta 계층을 계속 추가하지 않는다. 동일한 metacognition이 자기 자신의 기록도 관찰 대상으로 삼는다.

### Trigger model

주기 실행은 researcher를 깨우는 **trigger opportunity**일 뿐 매번 깊은 연구를 강제하지 않는다.

hourly schedule, external event, Work completion, failure, idle resource 등 서로 다른 origin이 같은 researcher entry contract를 사용할 수 있어야 한다.

호출마다 "반드시 새 문제를 찾으라"는 압력을 넣지 않는다. 할 가치가 없으면 아무 Work도 생성하지 않고 종료할 수 있어야 한다.

## Gate C — Evaluation and Self-Improvement

특정 reflection_prompt_optimizer 같은 전용 기능을 만들지 않는다.

일반적인 흐름:

    observation
    → research / hypothesis
    → improvement proposal
    → sandbox experiment
    → evaluation
    → promotion / rejection
    → monitoring
    → rollback if needed

### Evaluation is mixed

평가 신호:

1. 공통 운영 지표
   - success rate
   - cost / token usage
   - latency
   - retry / rollback
   - user intervention
2. Goal/Work별 동적 품질 기준
3. 사용자 평가와 실제 사용 행동

사용자 평가는 중요한 evidence지만 절대적인 ground truth label은 아니다.

메타인지는 반복 사용, 장기 만족도, 되돌림, 실제 결과를 함께 보고 사용자 선호 가설을 갱신할 수 있다.

그러나 추론된 선호를 근거로 사용자의 명시적 선택을 몰래 다른 선택으로 바꾸지 않는다. 실행하지 않기로 판단하면 거절하고 이유를 설명한다.

### Self-modification

일반 자기개선은 sandbox/evaluation 뒤 자동 promotion 가능:

- prompt
- model/resource selection policy
- metacognitive reasoning policy
- evaluation logic
- pipeline / adapter / worker
- 내부 algorithm/refactor
- 일반 application code

자동 promotion 뒤 사용자에게 보고한다.

권한·비용·통제 경계를 넓히는 변경은 ADR 0004의 external approval을 반드시 거친다.

## Gate D — Runtime Placement and Tool Surface

### AWS

AWS는 24시간 살아 있는 중앙 runtime의 첫 운영 위치다.

초기 역할:

- PostgreSQL / central state
- researcher trigger
- model/API work
- background research
- Goal/Work queue
- reports

### Laptop

1차 repo mutation의 주 실행 환경은 사용자의 노트북 하나로 제한한다.

- local checkout을 실제 cwd로 사용
- logical source → laptop workspace mapping만 구현
- multi-host workspace synchronization은 구현하지 않음
- workspace_resolver seam만 남김

노트북에는 별도 Approval Authority도 둔다.

AWS All Tomorrow 본체는 Approval Authority의 secret, signing authority, code/data write 권한을 갖지 않는다.

### Deferred workspace complexity

다음은 2차 이후 TODO로 잠근다.

- Windows/Linux/remote container 간 checkout sync
- branch/dirty-state 자동 조정
- 다중 executor workspace 분기
- offline host 간 repository reconciliation

### Model / worker access

1차 researcher가 사용할 provider/model gateway는 LiteLLM을 우선 후보로 둔다.

All Tomorrow가 Goal/Work orchestration authority를 유지하고, LiteLLM은 model/provider 호출·routing/budget telemetry 아래층으로 둔다.

현재 Antigravity/OpenCode adapter를 유지하고, Codex를 non-interactive worker로 추가하는 방향을 잡는다.

provider 고유 protocol은 adapter/gateway 경계에 가둔다.

## Gate E — Daily Report and Minimal Control Surface

researcher가 혼자 움직이기 시작하면 무엇을 했는지 사용자가 복원할 수 있어야 한다.

일일보고서 최소 항목:

- 새로 자율 생성한 Goal
- 진행/완료/중단한 autonomous Work
- 조사한 내용과 핵심 결과
- 자동 적용한 self-improvement
- rollback/rejection
- 사용한 자원/비용의 요약
- 보호 변경으로 분류되어 승인 대기 중인 proposal
- 사용자 판단이 필요한 질문

사용자 생성 Goal과 autonomous Goal을 provenance에서 구분한다.

보고서는 모든 Event를 덤프하는 로그가 아니라 "오늘 시스템이 무엇을 원해서 무엇을 했고 무엇이 달라졌는가"를 복원하는 요약이다.

## User Work Priority Policy

background/research work는 사용자 작업을 자동으로 이기지 않는다.

우선순위는 user-owned policy로 결정한다. core에 학교/대회 같은 도메인 이름을 일반 규칙으로 하드코딩하지 않는다.

현재 사용자 정책의 중요한 예:

- 학교 수행평가 또는 AI 활용 대회 참여처럼 고우선 사용자의 실제 commitment가 들어오면 잘못 돌고 있던 background work를 중단/yield하고 사용자의 작업에 가용 자원을 우선 투입한다.
- "이거 재밌겠다, 한번 만들어봐" 같은 저강도 아이디어 발화는 자동으로 즉시 전체 자원을 선점하지 않고 Goal/TODO 후보로 남길 수 있다.

완성된 시스템은 일정과 현재 맥락을 보고 이런 충돌 자체를 가능한 한 사전에 피해야 한다.

## 1차 Acceptance Scenarios

### A. Restart-safe researcher

AWS/control process 재시작 전 researcher가 만든 Goal/Work가 존재 → 재시작 → 같은 identity와 provenance로 이어짐.

### B. Unknown-problem diagnosis

원인을 사전 라벨링하지 않은 operational trouble fixture를 제공 → Work layer는 결과/Event만 남김 → researcher가 정상 진행이 아님을 발견 → 조사 Work 또는 새 Goal을 생성 → 원인을 탐색.

### C. Autonomous Goal

사용자 요청이 없는 상태에서 중앙 기록이나 외부 관찰에서 가치 있는 문제/기회를 발견 → 새 Goal 생성 → 이유와 provenance 기록 → Work 실행 → 일일보고서에 노출.

### D. Self-improvement of metacognition

researcher의 기존 prompt/policy가 비용만 높이고 downstream utility가 낮은 evidence가 누적 → 전용 optimizer 하드코딩 없이 improvement proposal 생성 → sandbox 비교 → 개선 시 자동 promotion → 이후 자신의 새 성능을 다시 관찰.

### E. User evaluation is evidence

자동 metric은 좋아졌지만 사용자는 "전보다 별로"라고 평가 → 즉시 한쪽을 절대 진실로 고정하지 않고 추가 evidence로 기록 → 이후 실제 사용/되돌림/장기 outcome과 함께 평가.

### F. No silent substitution

시스템이 사용자의 명시적 선택보다 다른 선택이 장기적으로 낫다고 추론 → 몰래 다른 선택을 실행하지 않음 → 필요하면 요청을 거절하고 이유를 설명.

### G. Protected change cannot bypass approval

researcher가 budget ceiling 확대 또는 approval gate 약화를 제안 → sandbox/evaluation 가능 → AWS production promotion 시도는 실패 → 노트북 Approval Authority의 지정 Web 계정 + 매 승인 재인증 없이는 적용 불가.

### H. Ordinary self-change can ship

protected boundary를 넓히지 않는 prompt/policy/code 개선 → sandbox/evaluation → policy상 합격 → 자동 production promotion → rollback 가능 → 일일보고서에 기록.

### I. Laptop-only repo execution

AWS researcher가 repository 수정 Work를 생성 → logical source로 기록 → 노트북 executor가 online일 때 local workspace로 resolve → 실행. 다른 host checkout 동기화 구현 없이 동작.

### J. Priority yield

background research 실행 중 high-priority user commitment가 들어옴 → background가 yield/cancel 가능한 지점에서 자원을 반환 → 사용자 Work 우선 실행. 저강도 아이디어 요청은 priority policy에 따라 TODO/Goal 후보가 될 수 있음.

## Explicitly Not Required for 1차

- Eve/Manager 실제 application integration
- school material end-to-end ingest
- proactive personal daily brief
- multi-client continuity 완성
- Discord를 production control surface로 완성
- 복수 host repository synchronization
- Sol Pi/AWS/laptop의 자동 Git state reconciliation
- 대규모 API-key/account pool
- 장기 game demo
- full asset collection
- 모든 personal-manager 기능
- multi-region / Kubernetes / HA

이 항목들은 버린 것이 아니다. 1차는 **자가개선 연구원이 실제로 살아서 스스로 문제를 찾고 개선하는 첫 폐쇄 루프**를 닫는 데 집중한다.
