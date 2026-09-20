# 3.3C — Multi-Executor Workspace

## 선행
3.3B + Stage2 workspace/routing

## 구현 위치
- 확장: src/all_tomorrow/workspaces.py
- tests/integration/test_multi_executor.py

states: unavailable/provisioning/ready-clean/ready-dirty/busy/offline/reconciliation-required.
source/branch/HEAD/dirty/root/provisioning provenance.

Requirements:
- S3-33C-01 offline freshness
- S3-33C-02 dirty checkout 자동 reset 금지
- S3-33C-03 source mismatch reject
- S3-33C-04 host 추가에 core name branch 없음
