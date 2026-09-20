# 2.4C — Fallback & Cross-System Mutation

## 구현 위치
- 새: src/all_tomorrow/cross_system.py
- adapters/source-specific modules
- tests/integration/test_cross_system.py

failure class에 따라 same Run recovery vs new Run fallback.
AMBIGUOUS_EFFECT는 alternate resource blind replay 금지.
source mutation은 expected version + authorization + resulting hash를 기록.
optional CompensationSpec 사용.

Requirements:
- S2-24C-01 resource unavailable→new Run fallback provenance
- S2-24C-02 ambiguous mutation blind fallback 0
- S2-24C-03 source owner optimistic version conflict
- S2-24C-04 compensation도 새 authorized mutation
