# Stage 1.6 — Acceptance

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01~05 완료

이 파일은 Stage 1 완료 판정의 local index다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 06A | Acceptance Fixtures | 선행작업 대기 | 아니오 | 01~05 완료 | [06a](06-acceptance/06a-test-fixtures.md) |
| 06B | End-to-End Scenarios | 선행작업 대기 | 아니오 | 06A | [06b](06-acceptance/06b-end-to-end.md) |
| 06C | Stage Close | 선행작업 대기 | 아니오 | 06B 전체 통과 | [06c](06-acceptance/06c-stage-close.md) |

mock/unit test만으로 Stage 1을 개발완료 처리하지 않는다.
