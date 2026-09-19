# Stage 1.5 — Daily Report and User Priority

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 02 Researcher Loop 완료
- 추가 의존성: durable execution bridge, model wiring, AWS runtime

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 05A | Report Projection & Store | 선행작업 대기 | 아니오 | 02 |
| 05B | Daily Report Composer | 선행작업 대기 | 아니오 | 05A + model wiring |
| 05C | User-Owned Priority Policy | 선행작업 대기 | 아니오 | durable bridge + 02 |
| 05D | Report Trigger & Minimal Access | 선행작업 대기 | 아니오 | 05A + 05B + AWS |
| 05E | Acceptance | 선행작업 대기 | 아니오 | 05A~05D |

## Priority 경계

P0~P6 의미는 All Tomorrow policy가 소유한다.

실제 execution ordering은 DurableExecutionPort adapter가 DBOS priority 등으로 변환한다.

학교/대회 문자열이나 DBOS queue status를 priority policy에 하드코딩하지 않는다.

## Report

report는 Event dump가 아니라 source-backed projection + summary다.

LLM 실패 시 deterministic fallback을 유지한다.
