# 2.2B — Store-backed Control API

## 선행
2.2A + 2.1

## 구현 위치
- 수정: src/all_tomorrow/web.py
- 새: src/all_tomorrow/api/control.py
- tests: tests/test_control_api.py

## Surface
Request create/read, Goal/Work/Run view, cancel, Question answer, Artifact fetch, report read, repair queue read.

모든 object fetch/mutation에 user/project authorization.

## Requirements
- S2-22B-01 in-memory WebState가 authority 아님
- S2-22B-02 object-id guessing cross-user access 실패
- S2-22B-03 cancel/answer가 Delivery intent 생성
- S2-22B-04 API version fixture
