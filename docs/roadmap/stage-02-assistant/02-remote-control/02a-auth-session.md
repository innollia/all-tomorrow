# 2.2A — Authentication & Session

## 구현 위치
- 새/수정: src/all_tomorrow/auth.py
- migration: migrations/00xx_auth.sql
- tests: tests/security/test_auth.py

## 계약
password KDF 또는 external auth provider를 00E/Stage2 시작 전 확정.
Secure/HttpOnly/SameSite, CSRF, rotation, idle/absolute expiry, revoke, brute-force limit.

## Requirements
- S2-22A-01 fixation/CSRF/replay 실패
- S2-22A-02 logout/revoke 즉시 반영
- S2-22A-03 user role owner/editor/viewer enforcement
- S2-22A-04 raw password/session secret logs 0
