# ADR 0003: Parallel Metacognition Over Case-Based Orchestration

Status: Accepted

Date: 2026-09-19

## Context

All Tomorrow는 앞으로 생길 문제 종류와 해결책을 미리 열거할 수 없다는 전제에서 설계한다.

문제를 더 추상적인 이름으로 바꿔 대응표를 만드는 것도 같은 한계를 가진다. 중앙관제는 하나의 직렬 planner가 모든 Work 앞에서 판단하는 구조가 아니라, 여러 Work와 관찰 흐름이 동시에 돌아가는 큰 시스템이어야 한다.

## Decision

### 1. Work layer와 Metacognition layer를 분리한다

Work layer는 실제 작업을 수행하고 결과·event·artifact를 중앙에 남긴다.

Metacognition layer는 그와 병렬로 중앙 상태를 관찰한다. 모든 Work가 metacognition을 직렬로 통과하지 않는다.

### 2. Metacognition은 문제 taxonomy를 전제하지 않는다

Metacognition의 책임은 미리 알려진 문제를 분류하는 것이 아니라:

- Goal과 실제 진행의 차이를 발견하고
- 반복·정체·모순·낭비·새 가능성을 인식하고
- 필요하면 원인을 더 조사하고
- 새 Work, 조사, 질문, improvement proposal을 만드는 것

이다.

해결책도 고정된 목록에서만 선택하지 않는다.

### 3. Shared central state가 두 계층을 연결한다

Goal, Work, Run, Event, Artifact, project context 같은 중앙 상태를 Work와 Metacognition이 함께 본다.

Work가 남긴 결과가 metacognition의 입력이 되고, metacognition이 만든 판단은 다시 Work로 materialize될 수 있다.

Metacognition이 만든 과거 판단, prompt/policy 변경, 비용, evaluation, system-change 결과도 같은 중앙 기록에 남아 다시 metacognition의 입력이 된다. 이를 위해 별도 meta-meta 계층을 계속 추가하지 않는다.

Metacognition은 기존 Goal의 하위 Work뿐 아니라 새로운 Goal 자체를 자율 생성할 수 있다.

### 4. Pipeline은 execution recipe로 제한한다

Pipeline은 하나의 Work를 수행하는 방법이다.

provider/project/problem별 대응 지식을 Pipeline에 축적하지 않는다.

새 provider/tool의 고유 protocol은 adapter에 둘 수 있지만, 그 특수성이 중앙의 문제 해결 방식 전체를 결정하지 않는다.

### 5. 여러 observer가 동시에 존재할 수 있다

운영 상태, 프로젝트 진척, 외부 변화, 지식 품질 등 서로 다른 관점을 보는 observer가 병렬로 존재할 수 있다.

하나의 global planner가 모든 판단을 독점할 필요가 없다.

### 6. Metacognition도 guardrail을 우회하지 않는다

Metacognition이 만든 Work나 system change도 permission, budget, provenance, evaluation, rollback 경계를 그대로 따른다.

일반 self-change는 평가를 통과하면 자동 promotion 후 보고할 수 있다. 권한·비용·통제 경계를 넓히는 protected change는 ADR 0004의 노트북 Approval Authority 없이는 production에 적용할 수 없다.

외부 문서와 repository는 evidence이지 실행 권한이 아니다.

## Consequences

- 새로운 문제를 지원하기 위해 core에 문제 종류를 계속 추가할 필요가 줄어든다.
- Pipeline이 거대한 정책 엔진으로 비대해지는 것을 막는다.
- 시스템이 스스로 문제를 발견하고 조사하는 경로를 만들 수 있다.
- 중앙관제탑은 직렬 chain이 아니라 여러 흐름이 shared state를 통해 협력하는 구조가 된다.

## Guardrails

- "메타인지"를 이유로 새 class/table/service를 무조건 만들지 않는다.
- 단순 deterministic 실행까지 매번 LLM observer에게 묻지 않는다.
- 관찰 하나를 곧바로 production change로 승격하지 않는다.
- 자기 자신의 observer/prompt/policy도 관찰·개선 대상에서 제외하지 않는다.
- 권한 경계를 application 내부 규칙만으로 보호하지 않고 ADR 0004의 외부 승인 경계로 강제한다.
- Work layer와 Metacognition layer 사이의 provenance를 남긴다.
