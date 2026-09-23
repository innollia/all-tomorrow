# 3.4A — Dynamic Work Graph

## 구현 위치
- 새: src/all_tomorrow/work_graph.py
- migration: migrations/00xx_work_graph.sql
- tests: tests/test_work_graph.py

relations: parent/child, depends_on, blocks, supersedes, generated_by.
cycle reject.
dependency outcome에 따른 WAITING/replan.

## BLOCKED 결정
별도 BLOCKED enum을 추가하지 않고 1차는 Work WAITING + wait_reason=dependency_blocked를 사용한다.
필요성이 실제 증명되면 schema ADR로 승격.

Requirements:
- S3-34A-01 cycle reject
- S3-34A-02 dependency failure를 dependent success/failure로 위조하지 않음
- S3-34A-03 dynamic child도 budget/dedup
