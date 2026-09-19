# Stage 1.2 — Researcher Loop

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01-durable-kernel 완료
- 다음으로 여는 작업: Evaluation & Self-Improvement, Daily Report

## Goal

작업 계층 옆에서 중앙 상태를 관찰하고, 사전에 이름 붙이지 않은 문제·기회를 발견해 Work 또는 새 Goal을 만드는 실제 researcher를 만든다.

## Read with

- ../../decisions/0003-generic-planning-over-hardcoded-pipelines.md
- 01-durable-kernel.md

## Inputs

- Goal / Work / Run / Event / Artifact
- 자신의 이전 observation/decision
- 자신이 만든 Goal/Work
- prompt / policy / model-selection 기록
- 비용/latency/retry
- evaluation 결과
- 사용자 평가와 이후 실제 사용 결과

## Outputs

필요하면 다음을 만들 수 있다.

- 조사 Work
- 진단 Work
- 실험 Work
- 기존 Work revision
- 새 Goal
- improvement proposal
- NEED_USER

기존 Goal 하위 Work만 만들도록 제한하지 않는다.

## Trigger Semantics

trigger는 깨어날 기회이지 매번 비싼 reasoning을 강제하는 명령이 아니다.

초기 origin 후보:

- hourly wake
- Work completion/failure
- external event
- idle resource
- system-generated wake

할 가치가 없으면 no-op 종료 가능해야 한다.

## Recursion Rule

meta → meta² → meta³ 같은 별도 계층을 만들지 않는다.

같은 metacognition mechanism이 자기 자신의 과거 활동도 관찰한다.

## Runaway Control

특정 problem taxonomy를 하드코딩하지 않되, autonomous lineage가 무한히 Work를 증식시키지 못하도록 공통 budget/lease/cancellation/provenance를 적용한다.

## Done When

1. 원인을 사전 라벨링하지 않은 반복 실패/정체 fixture에서 이상 발견
2. 추가 조사 Work 또는 새 Goal 생성
3. 정상 상태에서는 불필요한 Work 없이 종료 가능
4. researcher 생성 Goal/Work에 origin/provenance 존재
5. 자기 자신의 이전 metacognitive result를 다음 관찰에서 읽을 수 있음
