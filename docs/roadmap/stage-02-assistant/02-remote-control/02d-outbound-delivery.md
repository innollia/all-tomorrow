# 2.2D — Outbound Delivery Surface

## 목적
질문/보고/알림의 생성과 실제 사용자 전달을 분리한다.

## 구현 위치
- 새: src/all_tomorrow/outbound.py
- 새: src/all_tomorrow/storage/outbound_store.py
- migration: migrations/00xx_outbound.sql
- tests: tests/test_outbound.py

## 핵심
OutboundDelivery contract.
channel binding, idempotency, retry, delivery receipt, expiry, opt-out.

## Requirements
- S2-22D-01 retry duplicate message 방지
- S2-22D-02 Question record 생성≠delivery success
- S2-22D-03 sensitive content channel policy
- S2-22D-04 failed delivery가 Work/Question state를 위조하지 않음
