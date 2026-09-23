# 3.2A — Trigger Store & Scheduler

## 구현 위치
- 새: src/all_tomorrow/triggers.py
- 새: src/all_tomorrow/storage/trigger_store.py
- migration: migrations/00xx_triggers.sql
- tests: tests/test_triggers.py

TriggerRecord + TriggerDelivery.
recurring/one-shot/system schedule.
timezone, logical_fire_key, misfire, revision, cancel/update.

Requirements:
- S3-32A-01 duplicate fire→Work 1개
- S3-32A-02 old revision fire 무효
- S3-32A-03 DST fold/gap
- S3-32A-04 bounded catch-up
