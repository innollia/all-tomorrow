# AGENTS.md

매 작업 시작 전 관련 roadmap 상태표를 확인하고, 종료 전 실제 진행상태에 맞게 반드시 갱신한다.

- 전체: docs/roadmap.md
- Stage: 해당 docs/roadmap/stage-*/index.md
- 하위 packet이 있으면 가장 가까운 local index도 갱신
- 상태: 개발중 / 개발완료 / 시작안했음 / 선행작업 대기

## Plan contract

00B 이후 roadmap 구현은 다음 공통 계약을 먼저 따른다.

- docs/roadmap/plan-verification-contract.md
- docs/roadmap/domain-contracts.md
- docs/roadmap/failure-recovery-contract.md
- docs/roadmap/data-security-artifact-contract.md

계획서의 제목이나 테스트 개수만 보고 완료를 판단하지 않는다. requirement별 관측 가능한 증거와 요구 evidence level이 충족되어야 한다.

상위 identity/ownership/retry/security contract가 바뀌면 이미 작성되거나 완료된 downstream packet도 재검토한다.

## Stage 0 gate

docs/roadmap.md에서 Stage 0가 개발완료가 아니면 Stage 1의 기존 세부 packet은 구현하지 않는다.
Stage 1 문서에 남은 custom queue/lease/LLM-client 지시는 Stage 0의 재작성 대상이며 더 높은 우선순위의 구현 지시가 아니다.
