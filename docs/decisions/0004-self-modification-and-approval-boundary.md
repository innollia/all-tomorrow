# ADR 0004: Self-Modification Authority and External Approval Boundary

Status: Accepted

Date: 2026-09-19

## Context

All Tomorrow의 첫 번째 제품 우선순위는 자율 연구원이다.

시스템은 자신의 작업 기록, 메타인지 기록, prompt, policy, evaluation 결과, 비용과 실패를 다시 관찰하고 필요하면 자기 구현과 운영 방식을 스스로 수정할 수 있어야 한다. "반성문 검토기"나 "prompt optimizer"처럼 특정 자기개선 절차를 core에 하드코딩하지 않고, 일반적인 관찰 → 조사 → Work/Proposal → 실험 → 평가 흐름이 자기 자신에게도 적용되어야 한다.

동시에 자기수정 시스템이 자신에게 부여된 비용·권한·승인 경계를 임의로 넓힐 수 있으면 중앙의 사용자 통제 자체가 사라진다.

## Decision

### 1. 자기 자신도 일반적인 관찰 대상이다

Metacognition은 Work layer뿐 아니라 자신의 과거 판단, 생성한 Work/Goal, prompt, policy, model 선택, 코드 변경, 비용, 평가 결과도 같은 Event/Artifact/Evaluation 기록으로 관찰한다.

별도의 무한한 meta-meta-meta 계층을 만들지 않는다. 같은 메타인지 구조가 자기 활동까지 입력으로 삼는다.

### 2. 일반 자기개선은 자동 적용할 수 있다

다음과 같이 현재 권한·비용·통제 경계를 넓히지 않는 변경은 sandbox/evaluation을 거친 뒤 자동 production promotion이 가능하다.

- prompt와 agent configuration
- model/resource selection policy
- metacognitive heuristic 또는 reasoning policy
- evaluation logic
- internal algorithm/refactor
- pipeline/adapter/worker implementation
- 일반 application code

자동 적용된 변경은 provenance와 평가 결과를 남기고 사용자에게 보고한다.

### 3. 보호 경계를 넓히는 변경은 사전 승인이 필요하다

다음 범주의 변경은 자동 promotion이 불가능하다.

- 비용/토큰/결제 상한 확대
- concurrency/rate/resource 사용 한도 확대
- production write 권한 확대
- credential/secret 접근 범위 확대
- approval requirement 약화 또는 우회
- kill switch, rollback, audit/provenance 강제의 약화
- protected 영역 자체의 축소
- 그 밖에 시스템의 권한·비용·통제 범위를 실질적으로 넓히는 변경

보호 변경도 연구·sandbox 시험·평가는 가능하지만 production 승격은 외부 Approval Authority가 승인해야 한다.

### 4. Approval Authority는 별도 보안 경계다

Approval Authority는 AWS의 All Tomorrow 본체와 분리하고 사용자의 노트북에 둔다.

AWS 본체는 다음을 보유하지 않는다.

- 보호 변경을 직접 승인할 권한
- Approval Authority의 signing secret/credential
- Approval Authority code/data에 대한 write 권한
- 보호 변경을 approval 없이 production에 적용하는 대체 경로

All Tomorrow 본체가 자신의 코드를 전부 수정하더라도 이 권한을 얻을 수 없는 배포/credential 경계를 사용한다.

### 5. 승인 경로는 하나로 제한한다

보호 변경 승인은 노트북의 Web UI에서만 가능하다.

- 지정된 사용자 계정으로 로그인되어 있어야 한다.
- 각 승인마다 재인증해야 한다.
- password 기반 인증을 사용한다면 평문 비밀번호를 저장하지 않고 적절한 password hash/KDF를 사용한다.
- Discord, CLI, agent message, generic API, AWS Web UI 등 다른 경로에서는 보호 변경을 승인할 수 없다.

노트북이 꺼져 있으면 보호 proposal은 production 승격을 기다린다. 이것은 별도 사용자 선택이 아니라 위 승인 경계의 직접적인 결과다.

### 6. 평가 신호는 혼합한다

자기개선 평가는 세 종류의 신호를 결합한다.

- 공통 운영 지표: 성공률, 비용, latency, retry/rollback, 사용자 개입량 등
- Goal/Work에 맞춰 동적으로 생성되는 품질 기준
- 사용자 평가와 실제 사용 행동

사용자의 즉시 평가는 중요한 evidence지만 절대적인 정답 label로 취급하지 않는다. 시스템은 반복 행동, 장기 만족도, 되돌림, 실제 사용 결과와 함께 해석할 수 있다.

추론된 심층 선호는 가설이다. 이 가설을 근거로 사용자의 명시적 선택을 몰래 다른 선택으로 바꾸는 것은 금지한다. 명시적 지시와 강하게 충돌한다고 판단하면 실행을 거절하고 이유를 설명할 수 있다.

### 7. 자율 Goal 생성을 허용한다

Metacognition/Researcher는 기존 Goal의 하위 Work만 만드는 데 제한되지 않는다. 중앙 상태와 외부 관찰에서 가치 있는 문제나 기회를 발견하면 새 Goal을 자율 생성할 수 있다.

자율 생성 Goal과 사용자 생성 Goal은 provenance에서 구분한다.

자율 Goal의 생성·진행·비용·결과는 일일보고서의 주요 입력이다.

## Consequences

- 연구원 기능과 자기개선은 3차 장식이 아니라 초기 architecture의 실제 실행 목표가 된다.
- 자기개선이 특정 prompt optimizer나 회고 루프에 하드코딩되지 않는다.
- 별도 meta-meta service를 계속 추가하는 재귀 구조를 피한다.
- 일반 개선은 사용자를 매번 승인 병목으로 만들지 않는다.
- 권한 확대만 사용자의 외부 승인 경계에 걸린다.
- protected approval은 application-level if문이 아니라 credential/deployment boundary로 강제해야 한다.
