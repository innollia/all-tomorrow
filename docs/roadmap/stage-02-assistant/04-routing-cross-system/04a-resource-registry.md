# 2.4A — Resource Registry

## 구현 위치
- 새: src/all_tomorrow/resources.py
- 새: src/all_tomorrow/storage/resource_store.py
- tests: tests/test_resources.py

ResourceRecord/ToolDescriptor/WorkerDescriptor/ModelRoute를 등록.
health freshness, capability, authority, cost/quota, version.

Requirements:
- S2-24A-01 stale health 처리
- S2-24A-02 provider 이름별 core branch 금지
- S2-24A-03 unknown quota/cost conservative
