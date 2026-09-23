# 2.3A — Context Pack

## 구현 위치
- 새: src/all_tomorrow/context_pack.py
- tests: tests/test_context_pack.py

## 핵심
objective, explicit constraints, source refs, decisions, open state, artifacts/lessons, freshness, token/byte budget.
data content와 control instruction authority를 분리.

## Requirements
- S2-23A-01 deterministic bounded selection
- S2-23A-02 omitted refs summary
- S2-23A-03 owner conflict silent merge 금지
- S2-23A-04 prompt injection/untrusted content authority 확대 실패
