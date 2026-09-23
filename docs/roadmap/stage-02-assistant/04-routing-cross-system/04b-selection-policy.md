# 2.4B — Selection Policy

## 구현 위치
- 새: src/all_tomorrow/routing_policy.py
- config: config/routing-policy.example.yaml
- tests: tests/test_routing_policy.py

pipeline: hard filter→rank→select.
policy version/ref 기록.
explicit user resource choice는 inferred preference로 override 금지.
starvation/aging policy를 priority policy와 함께 정의.

Requirements:
- S2-24B-01 authority/capability hard filter
- S2-24B-02 insertion order 비의존
- S2-24B-03 P0~P6 의미/aging/starvation 확정
- S2-24B-04 explicit resource constraint 보존
