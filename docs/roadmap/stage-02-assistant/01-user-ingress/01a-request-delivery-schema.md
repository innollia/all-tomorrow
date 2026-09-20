# 2.1A — Request / Delivery Schema

## 목적
canonical Request/Delivery/inbound dedup schema를 구현한다.

## 구현 위치
- 새: src/all_tomorrow/requests.py
- 새: src/all_tomorrow/storage/request_store.py
- migration: migrations/00xx_requests.sql
- tests: tests/test_request_store.py

## 핵심
Request와 Delivery 분리.
source_event_id/idempotency_key unique scope.
attachment는 ArtifactRef.
API idempotency key retention/window 저장.

## Requirements
- S2-21A-01 concurrent duplicate delivery → Request 1개
- S2-21A-02 delivery history는 여러 ingress를 보존
- S2-21A-03 key namespace/version/expiry 저장
- S2-21A-04 cross-user key collision 없음
