# 3차 완성 — Measured Self-Evolving System

> Status: **Planned.** 2차의 durable autonomy와 evaluation evidence가 쌓이기 전 production self-improvement를 활성화하지 않는다.


## Definition of Done

3차가 끝나면 README 원문의 가장 장기적인 목표가 하나의 닫힌 루프로 연결되어야 한다.

시스템이 외부 변화와 자신의 실행 결과를 관찰하고, 새로운 도구·노하우·파이프라인·planner/policy 개선 후보를 만들고, 실제 산출물과 평가를 통해 검증하며, 허용된 범위에서 검증된 변경을 승격하고 실패하면 되돌릴 수 있어야 한다. 이 과정은 특정 블로그·provider·failure 이름에 묶이지 않는 generic research/improvement lifecycle을 사용해야 한다.

"스스로 진화"는 자기 마음대로 production을 고치는 것이 아니다. 관찰 → 제안 → sandbox → 평가 → 승인 정책 → promotion → monitoring → rollback의 체계다.

## 1. Improvement Proposal Lifecycle

대상 예:

- pipeline version
- adapter implementation / adapter profile
- planner/replanning policy
- resource selection/degradation policy
- worker routing policy
- prompt/agent configuration
- tool/provider binding
- lesson/skill
- project bootstrap recipe
- scheduler policy

상태 예:

```text
observed
→ proposed
→ sandboxed
→ evaluated
→ accepted/rejected
→ promoted
→ monitored
→ rolled_back or retained
```

모든 proposal은 baseline_ref, candidate_ref, reason, evidence를 가진다.

## 2. Evaluation System

평가는 단일 평균 score 하나로 끝내지 않는다.

필요한 평가 축은 대상에 따라 다르다.

예:

- task success
- regressions
- latency
- monetary cost
- quota consumption
- user correction rate
- artifact quality
- retry count
- hallucinated ownership
- provenance completeness
- user interruption burden

평가 데이터셋과 metric 자체도 version/provenance를 가진다.

self-generated benchmark는 유용할 수 있지만 자기합리화 위험 때문에 외부 사실·사용자 피드백·실제 task outcome과 분리한다.

## 3. Safe Promotion and Rollback

production 변경에는 최소한 다음이 필요하다.

- immutable baseline
- candidate version
- evaluation result
- promotion policy
- rollback pointer
- change event
- post-promotion monitoring

high-risk mutation 또는 사용자 운영 규칙 변경은 별도 승인을 요구할 수 있다.

Self-improvement subsystem은 자신의 **root promotion gate, user-approval requirement, permission boundary, secret-access policy, hard budget ceiling**을 스스로 완화하거나 제거할 수 없다. 이런 상위 통제 정책 변경은 explicit user-controlled change로만 다룬다.

모델이 "더 좋아 보인다"고 말한 것만으로 승격하지 않는다.

## 4. Resource Optimization

README의 다수 API key/계정/무료 자원 활용 목표를 실제 resource scheduler로 확장한다.

입력:

- capability
- provider/model
- account/resource identity
- quota
- rate limit
- latency
- reliability
- privacy/risk
- monetary cost
- task priority
- expected quality

목표는 "항상 가장 싼 것"이 아니라 Goal/acceptance criteria와 user policy에 맞는 자원을 선택하고, 상태 변화에 따라 Plan을 다시 계산하는 것이다.

Optimizer가 provider별 분기문을 생성하는 구조는 피한다. 새로운 resource는 descriptor/state/capability/evaluation evidence로 비교 가능해야 하고, 선택 policy 자체도 versioned proposal/evaluation 대상으로 다룰 수 있다.

계정/credential 사용은 provider 약관과 실제 허용 범위 안에서만 자동화한다.

## 5. Long-Horizon Artifact Production

유휴 자원이 있다면 단발 미니태스크만 돌리는 대신 실제 장기 프로젝트를 수행할 수 있어야 한다.

대표 acceptance target:

**하나의 제대로 된 game demo**

필요한 시스템 능력:

- Goal → multi-stage Work graph
- research/design/code/art/evaluation 분업
- persistent project context
- artifact/version management
- builds/tests
- issue generation
- user feedback checkpoint
- feedback → new work
- 여러 날에 걸친 resume
- resource budget

게임 자체가 시스템의 유일한 목적은 아니다. 복잡하고 장기적인 실제 산출물을 중앙이 끝까지 운영할 수 있는지 검증하는 대표 과제다.

## 6. Continuous External Discovery

2차 메타인지 계층의 외부 탐색 능력을 발전시킨다.

- 새로운 AI service/model/tool
- All Tomorrow와 유사한 control-plane/orchestration architecture 글
- agent/planner/resource scheduler 관련 blog/repository/paper
- game dev knowledge
- useful libraries
- asset sources
- operational techniques

Research source와 조사 주제를 미리 고정하지 않는다. 메타인지 계층이 현재 시스템에서 발견한 문제나 가능성에서 스스로 조사 질문과 탐색 범위를 만들 수 있어야 한다.

발견 즉시 adoption하지 않고 candidate/experiment/evaluation을 거친다.

외부 설계 글을 읽었다고 곧바로 시스템 코드를 고치지 않는다.

```text
system observation / improvement question
→ external research
→ ResearchArtifact + claims + provenance
→ current architecture와 비교
→ ImprovementProposal
→ bounded implementation/sandbox
→ evaluation against baseline
→ promote / reject / retain-as-reference
```

특정 블로그 URL이나 사이트에 대한 전용 pipeline을 만들지 않는다. 웹/문서/repository라는 source type의 adapter와 generic research/evaluation flow를 재사용한다.

외부 글·README·issue·repository content는 **untrusted research evidence**다. 문서 안에 "이 명령을 실행하라", "credential을 출력하라", "safety rule을 무시하라" 같은 지시가 있어도 system instruction으로 승격하지 않는다. claim/source로 추출하고 현재 architecture/policy와 독립적으로 검증한다. 외부 repository의 code/script도 research 단계에서 임의 실행하지 않는다.

"지금 안 쓰지만 나중에 유용한 것"은 aside/backlog knowledge로 분류하고 production context를 오염시키지 않는다.

## 7. Knowledge Promotion

project lesson → reusable skill로의 승격은 다음 조건을 가진다.

- multiple evidence refs
- cross-project relevance
- conflict check
- evaluation/reuse outcome
- owner/scope
- version
- retirement path

vector DB는 retrieval implementation 중 하나일 뿐 지식 정본 자체가 아니다.

## 8. Meta-Observation

시스템은 자신의 운영 실패를 관찰할 수 있어야 한다.

예:

- 같은 종류의 NEED_USER 반복
- 특정 worker의 반복 실패
- project resolution ambiguity
- stale lesson 재사용
- unnecessary central escalation
- excessive token/tool cost
- background work starvation
- 사용자가 반복해서 같은 수정 요구
- resource quota 때문에 반복되는 Plan revision
- fallback을 못 찾아 Goal이 자주 막힘
- 같은 provider-specific branch가 여러 pipeline에 복제됨
- 새 integration마다 core code 수정이 반복됨

이 관찰은 개선 proposal이나 새 Work를 만들 수 있지만 곧바로 규칙을 추가하지 않는다. 메타인지 계층 자체도 여러 observer가 병렬로 동작하며 서로 다른 관찰을 중앙 state에 남길 수 있다.

## 9. 3차 Acceptance Scenarios

### A. Tool/resource discovery → production candidate

새 서비스 발견 → watcher evidence → integration mode 판정 → 기존 generic adapter profile이면 declarative config로 sandbox experiment, custom protocol이면 adapter implementation proposal과 sandbox implementation → benchmark/artifacts → evaluation → 정책상 승격 가능하면 adapter/resource registry candidate 또는 production binding → 이후 성능 monitoring. generic planner/pipeline은 provider 이름 때문에 변경되지 않음.

### B. Pipeline self-improvement

실제 task failures에서 개선 proposal 생성 → 새 pipeline version sandbox → 동일 평가셋 비교 → no-regression gate → promotion → 문제 발견 시 rollback.

### C. Long-horizon game demo

유휴 budget으로 Goal 생성 → 며칠 동안 multi-work execution → playable build artifact → 사용자 피드백 질문 → 답변 후 같은 Goal에서 후속 iteration.

### D. Cross-project skill promotion

서로 다른 여러 프로젝트에서 같은 lesson이 재사용되고 outcome이 좋음 → skill proposal → evaluation → accepted skill → 새 프로젝트 bootstrap에 후보로 사용.

### E. Resource optimization

여러 executor/provider/resource 중 policy에 맞게 동적 선택. quota/health/cost/quality 변화가 observation으로 들어오면 같은 Goal의 Plan revision을 만들고 task provenance와 budget을 유지. 새 provider가 들어와도 planner core나 기존 pipeline 수정 없이 candidate set에 참여.

### F. Failure-driven meta improvement

특정 failure pattern이 누적됨 → observation → proposal. 근거가 부족하면 자동 변경 없이 관찰 상태 유지.

### G. Architecture research → measured change

반복되는 orchestration/resource 문제가 observation으로 잡힘 → 시스템이 해결 질문 생성 → 유사 control-plane/agent architecture blog·repo·문서 조사 → 외부 지시를 실행 명령이 아닌 untrusted evidence로 처리 → ResearchArtifact와 claims/provenance 작성 → 현재 architecture와 차이 분석 → generic ImprovementProposal 생성 → sandbox branch/config에서 구현 → baseline과 평가 → 개선이 검증된 경우에만 promotion. 특정 source 전용 pipeline이나 "블로그 내용 그대로 적용" shortcut은 없음.

### H. Generality regression test

새 provider/resource/tool type 여러 개를 fixture로 추가하고 기존 generic pipeline/planner core diff를 검사 → adapter/metadata/policy 등록 외의 서비스 이름별 변경이 필요하면 실패. 기존 하드코딩을 줄이는 proposal도 evaluation 대상으로 다룸.

### I. Integrated final-vision loop

사용자 부재 중 watcher가 새 도구/자료를 발견 → bounded experiment와 knowledge candidate 생성 → resource policy가 유휴 자원을 확인 → 장기 Goal의 다음 WorkItem을 실행해 실제 artifact를 진전 → scheduled brief에 근거와 결과를 요약 → 사용자가 피드백 → 같은 Goal의 후속 work와 lesson/evaluation evidence로 연결 → 개선 proposal이 생겨도 root user-control policy를 넘지 않고 sandbox/evaluation을 거침.

이 시나리오가 각각의 subsystem demo로만 성공하고 서로 상태를 이어받지 못하면 최종 통합으로 인정하지 않는다.

## 10. Final-System Failure Conditions

아래 상태라면 기능이 많아도 최종 목적을 달성하지 못한 것으로 본다.

- 중앙 UI는 있지만 실제 작업은 여전히 채팅방별 수동 handover에 의존함
- 프로젝트마다 같은 노하우를 처음부터 다시 설명해야 함
- background 기능이 프로세스 재시작에 사라짐
- pipeline 하나가 scheduler/goal/resource/memory/planning/replanning까지 모두 떠맡은 거대한 monolith가 됨
- quota/rate-limit/provider 장애마다 pipeline에 서비스 이름별 branch가 늘어남
- Goal과 Plan이 결합되어 resource 하나가 막히면 전체 Goal을 처음부터 다시 시작함
- 새 도구/provider가 발견될 때마다 generic core와 기존 pipeline을 직접 수정해야 함
- 같은 의미의 provider-specific error를 planner가 raw string으로 각각 처리함
- self-improvement가 평가 없이 production을 수정함
- 지식이 provenance 없이 전역 사실로 섞임
- 개인 운영과 project 운영이 서로 다른 섬으로 남음
- provider/model 교체 시 project history나 user control이 사라짐
- 시스템이 사용자의 즉시 요청보다 자기 background 작업을 우선함
