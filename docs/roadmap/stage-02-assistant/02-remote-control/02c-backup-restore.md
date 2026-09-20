# 2.2C — Backup / Restore

## 선행
Stage1 AWS runtime + 2.2A

## 구현 위치
- ops/backup/ 또는 deployment runbook
- tests/acceptance/test_backup_restore.py

## 결정
RPO/RTO 숫자를 deployment ADR에서 확정.
app DB/durable state/artifact metadata를 별도 owner로 backup.
restore 후 cross-store reconciliation.

## Requirements
- S2-22C-01 backup artifact access/retention
- S2-22C-02 isolated restore
- S2-22C-03 RPO/RTO 실제 측정
- S2-22C-04 restored secret/session rotation policy
