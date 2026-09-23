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

## Priority semantics

- P0 — 즉시 중단 대응이 필요한 사용자 명시 긴급/안전/시간 임박 commitment
- P1 — 사용자 명시 high-priority 또는 가까운 hard deadline
- P2 — 현재 사용자가 직접 맡긴 active request
- P3 — 일반 scheduled/user-owned Work
- P4 — proactive personal/manager Work
- P5 — autonomous research/self-improvement
- P6 — opportunistic maintenance/discovery

동일 priority 안에서는 deadline, explicit ordering, age, enqueue time을 versioned policy로 사용한다.

### Aging / starvation

- P5/P6가 오래 대기하면 제한적으로 한 단계씩 aging 가능
- aging만으로 P2 이상이 되지 않음
- explicit user constraint/deadline 없이는 autonomous Work가 current active user request보다 위로 올라가지 않음
- P0/P1은 무제한 선점 권한이 아니라 non-interruptible mutation safety boundary를 여전히 준수

### Commitment mapping

- hard_commitment → P0/P1
- ordinary current request → P2
- scheduled user task → P3
- proactive brief/preparation → P4
- autonomous background → P5
- low-value maintenance/opportunistic discovery → P6
- "재밌겠다/나중에 해볼까"처럼 low-commitment idea는 즉시 실행 priority가 아니라 TODO/Goal candidate로 materialize 가능

policy version/ref를 모든 priority decision provenance에 기록한다.

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
