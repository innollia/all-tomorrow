# 05C — User-Owned Priority Policy

## Status

- 상태: **선행작업 대기**
- 선행조건: 01 Durable Execution Bridge + 02 Researcher Loop
- 지금 시작 가능: **아니오**

## 목적

사용자 commitment가 autonomous background work보다 우선하도록 semantic priority와 safe preemption policy를 정의한다.

## Inputs

- origin
- explicit priority
- commitment_level
- deadline/urgency
- interruptibility
- resource class
- authority/budget constraints
- provenance

domain 문자열 자체를 condition으로 쓰지 않는다.

## Policy

- hard_commitment user Work: P0/P1 candidate
- normal_request: context에 따른 active priority
- low_commitment_idea: TODO/Goal candidate, 즉시 실행 필수 아님
- autonomous research: 기본 background priority

실제 mapping 값은 versioned policy/config로 기록한다.

## Dispatch vs preemption

semantic priority와 durable backend mechanism을 구분한다.

### Pending dispatch

selected backend의 priority/delay mapping을 사용해 새 high-priority Work가 먼저 실행되도록 한다.

### Already running background Work

lease/heartbeat 반환 같은 custom queue 용어를 사용하지 않는다.

- interruptible + selected backend가 safe suspend/cancel boundary를 지원하면 cooperative yield request
- 현재 operation이 non-interruptible external mutation이면 reconciliation 가능한 boundary까지 강제 kill 금지
- backend가 pause를 지원하지 않으면 새 background Run 시작을 막고 현재 bounded operation 종료 후 user Work를 우선
- yield/cancel 여부와 이유는 Event/Run provenance로 남김

## Requirements

- hard commitment가 pending research보다 먼저 dispatch
- low-commitment idea가 자동 P0 아님
- running safe-yield 시 Work/Run provenance 유지
- non-interruptible mutation을 중간 kill하지 않음
- selected backend가 지원하지 않는 pause primitive를 core에서 가짜로 구현하지 않음
- policy version/ref 기록

## 완료조건

사용자 high-priority Work가 실제 resource dispatch에서 우선하며 preemption이 selected backend semantics와 충돌하지 않아야 한다.
