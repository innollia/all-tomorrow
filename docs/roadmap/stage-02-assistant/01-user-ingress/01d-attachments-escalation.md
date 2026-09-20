# 2.1D — Attachment & Escalation Policy

## 선행
2.1A

## 구현 위치
- 새: src/all_tomorrow/ingress_policy.py
- 수정: artifact adapter/store
- tests: tests/test_ingress_policy.py

## Attachment
bytes→temporary write→hash→immutable ArtifactRef.
Request row에 raw bytes 금지.

## Escalation
versioned deterministic preflight:
- durable execution 필요
- cross-project/resource mutation
- central state query/update
- background/restart-safe task
불명확한 mutation은 central resolution 또는 NEED_USER.

## Requirements
- S2-21D-01 artifact hash/provenance
- S2-21D-02 duplicate attachment dedup
- S2-21D-03 local/central policy version 기록
- S2-21D-04 untrusted attachment instruction이 authority 확대 못함
