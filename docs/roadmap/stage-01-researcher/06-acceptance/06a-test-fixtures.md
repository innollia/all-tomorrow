# 06A — Stage 1 Acceptance Fixtures

## Status

- 상태: **선행작업 대기**
- 선행조건: 01~05 구현 완료
- 지금 시작 가능: **아니오**

## 목적

acceptance를 사람이 눈으로 demo 보고 통과시키지 않고 reproducible fixture로 만든다.

## 추가 파일

- `tests/acceptance/conftest.py`
- `tests/acceptance/fixtures/`
- `tests/acceptance/test_stage1_researcher.py`
- `tests/acceptance/test_stage1_self_improvement.py`
- `tests/acceptance/test_stage1_authority.py`

## Fixture 원칙

- mock LLM fixture와 real integration mode 분리
- unlabeled trouble fixture는 "이건 quota 문제" 같은 답을 metadata에 미리 넣지 않음
- user feedback conflict fixture
- ordinary self-change fixture
- protected boundary change fixture
- laptop offline fixture
- high-priority user Work fixture

## 통과 규칙

unit mock만 통과했다고 Stage 1 완료로 표시하지 않는다.

PostgreSQL 실제 integration + AWS-like restart + laptop authority boundary를 포함.
