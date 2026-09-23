# 3.3B — Resource Ledger

## 구현 위치
- 새: src/all_tomorrow/resource_ledger.py
- migration: migrations/00xx_resource_ledger.sql
- tests: tests/test_resource_ledger.py

capacity/reservation/actual usage.
atomic reserve/release/reconcile.
unknown quota/cost conservative.

Requirements:
- S3-33B-01 concurrent reservation ceiling
- S3-33B-02 failed op actual cost 반영
- S3-33B-03 expired reservation release
- S3-33B-04 Stage1 lineage budget과 역할 중복 없음
