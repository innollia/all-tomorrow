# 00B-3 — Delivery & Reconciliation Protocol

## Status
- 상태: 선행작업 대기
- 선행조건: 00B-1
- 완료 후 열림: 00C

## 목적
Run start만이 아니라 Question answer, Trigger fire, Artifact attach, source mutation, outbound delivery까지 cross-store dual-write를 공통 protocol로 만든다.

## 구현 예정 위치
- 새: src/all_tomorrow/delivery.py
- 새: src/all_tomorrow/storage/delivery_store.py
- 새 migration: migrations/00xx_delivery.sql
- 테스트: tests/test_delivery_store.py
- integration: tests/integration/test_delivery_reconciliation.py

## DeliveryRecord
delivery-consistency-contract.md schema 사용.

## 우선 구현 seam
1. Run STARTING → durable start
2. Question ANSWERED → signal
3. Artifact finalized → ref attach
4. outbound Question/report delivery

Trigger/source mutation은 Stage 2/3에서 같은 primitive를 확장한다.

## Reconciliation
- DB lock/revision
- deterministic idempotency key
- existing external effect 조회
- CAS attach
- divergent result fail closed
- bounded attempts
- REPAIR_REQUIRED

## Requirements
- S0-00B3-01: app transaction + delivery intent atomic
- S0-00B3-02: concurrent reconciler same result로 수렴
- S0-00B3-03: ambiguous external effect blind replay 금지
- S0-00B3-04: exhausted delivery가 삭제되지 않고 repair surface로 이동
- S0-00B3-05: idempotency key scope/version/retention 정의

## 완료 증거
- delivery state machine
- SQL constraint/index plan
- crash-window sequence diagrams
