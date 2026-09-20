# Stage 1.5 — Daily Report and User Priority

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 02 Researcher Loop 완료
- 추가 의존성: 01 durable bridge, 04A model wiring, 04D AWS

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 05A | Report Projection & Store | 선행작업 대기 | 아니오 | 02 |
| 05B | Daily Report Composer | 선행작업 대기 | 아니오 | 05A + 04A |
| 05C | User-Owned Priority Policy | 선행작업 대기 | 아니오 | 01 + 02 |
| 05D | Report Trigger & Minimal Access | 선행작업 대기 | 아니오 | 05A + 05B + 04D |
| 05E | Acceptance | 선행작업 대기 | 아니오 | 05A~05D |

## Priority boundary

P0~P6 의미와 user commitment policy는 All Tomorrow가 소유한다.
실제 execution ordering/preemption mechanics는 00E selected DurableExecutionPort mapping으로 변환한다.

provider/backend queue status나 학교/대회 같은 domain 문자열을 core priority condition으로 사용하지 않는다.

## Report boundary

report는 immutable source-backed projection + summary다.

- logical period/timezone identity
- source watermark/version
- late evidence revision
- unknown cost/result 보존
- deterministic fallback

LLM 실패로 report state가 유실되지 않는다.
