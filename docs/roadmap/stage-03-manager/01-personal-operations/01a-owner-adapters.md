# 3.1A — Owner Adapters & Source Precedence

## 구현 위치
- 새: src/all_tomorrow/owners.py
- 새: src/all_tomorrow/storage/owner_refs.py
- tests: tests/test_owner_adapters.py

## 핵심
SourceRef 기반 canonical owner read/write.
derived summary는 owner truth overwrite 금지.
stale/conflict→refresh/UNKNOWN/NEED_USER.

Requirements:
- S3-31A-01 owner read/write provenance
- S3-31A-02 source precedence
- S3-31A-03 stale cache current truth 위조 금지
- S3-31A-04 role/authority enforcement
