# 3.2B — Webhook / Polling / Condition Watchers

## 선행
3.2A

## 구현 위치
- 새: src/all_tomorrow/triggers_webhook.py
- 새: src/all_tomorrow/watchers.py
- tests: tests/test_watchers.py

Webhook: signature, nonce/timestamp replay, size/type limits.
Watcher: durable cursor, edge-vs-level semantics, poll failure≠condition false.

Requirements:
- S3-32B-01 replay webhook duplicate 없음
- S3-32B-02 unauthenticated webhook reject
- S3-32B-03 restart cursor 유지
- S3-32B-04 repeated true storm 없음
