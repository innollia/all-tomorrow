# 05B — Daily Report Composer

## Status

- 상태: **선행작업 대기**
- 선행조건: 05A + 04A
- 지금 시작 가능: **아니오**

## 목적

source-backed structured facts를 사용해 사용자가 시스템의 행동과 결과를 복원할 수 있는 일일 보고서를 만든다.

## Sections

최소 output contract:

1. Autonomous Goals
2. User Work Progress
3. Research Findings
4. System Changes
5. Rollbacks / Rejections
6. Resource & Cost
7. Approval Pending
8. Needs User

## Composition

1. 05A projection facts 생성
2. deterministic section skeleton
3. LLM은 표현/압축/ordering 보조
4. source ref 없는 사실 추가 금지
5. LLM output의 claim→source mapping 검증
6. 실패/invalid output이면 deterministic fallback FINAL 생성 가능

LLM 성공 여부가 report durability를 결정하지 않는다.

## Bounded context

- source refs + precomputed structured facts 사용
- raw Event/history 무제한 prompt 금지
- report generation budget accounting
- sensitive source는 필요한 요약/ref만 사용하고 raw content telemetry 저장 금지

## Requirements

- source 없는 claim reject/fallback
- LLM unavailable fallback
- autonomous/user distinction
- pending approval/question 표시
- unknown cost=unknown
- late report revision이 prior report를 덮지 않음

## 완료조건

LLM 장애에도 생성 가능하고 각 substantive claim이 durable source ref로 추적되어야 한다.
