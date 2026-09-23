# 2.1B — Web / API Ingress

## 선행
2.1A

## 구현 위치
- 수정: src/all_tomorrow/web.py
- 새/수정: src/all_tomorrow/api/models.py
- tests: tests/test_web_ingress.py

## API
versioned request/response schema.
mutation endpoint는 idempotency semantics 명시.
old-client compatibility fixture 유지.

## Requirements
- S2-21B-01 authenticated user→canonical Request
- S2-21B-02 retry same key→same Request
- S2-21B-03 old API fixture compatibility
- S2-21B-04 unknown/new fields policy 고정
