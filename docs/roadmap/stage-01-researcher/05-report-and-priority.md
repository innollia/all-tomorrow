# Stage 1.5 — Daily Report and User Priority

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 02 Researcher Loop 완료
- 추가 의존성: 01 Durable Queue, 04A LiteLLM, 04D AWS Runtime

이 파일은 05 작업의 local index다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 05A | Report Projection & Store | 선행작업 대기 | 아니오 | 02 완료 | [05a](05-report-and-priority/05a-report-store.md) |
| 05B | Daily Report Composer | 선행작업 대기 | 아니오 | 05A + 04A | [05b](05-report-and-priority/05b-report-composer.md) |
| 05C | User-Owned Priority Policy | 선행작업 대기 | 아니오 | 01 queue + 02 | [05c](05-report-and-priority/05c-priority-policy.md) |
| 05D | Report Trigger & Minimal Access | 선행작업 대기 | 아니오 | 05A + 05B + 04D | [05d](05-report-and-priority/05d-report-trigger-and-access.md) |
| 05E | Acceptance | 선행작업 대기 | 아니오 | 05A~05D | [05e](05-report-and-priority/05e-acceptance.md) |

## 핵심 구조

- report는 Event dump가 아니라 source-backed projection + summary
- LLM 실패 시 deterministic fallback
- priority는 학교/대회 문자열이 아니라 user-owned commitment metadata로 동작
