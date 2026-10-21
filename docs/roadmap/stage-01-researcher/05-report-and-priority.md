# Stage 1.5 — Daily Report and User Priority

## Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 02 Researcher Loop 완료
- 추가 의존성: 01 durable bridge, 04A model wiring, 04D AWS

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 05A | Report Projection & Store | 개발중 | 아니오 | 02 |
| 05B | Daily Report Composer | 개발중 | 아니오 | 05A + 04A |
| 05C | User-Owned Priority Policy | 개발중 | 아니오 | 01 + 02 |
| 05D | Report Trigger & Minimal Access | 개발중 | 아니오 | 05A + 05B + 04D |
| 05E | Acceptance | 개발중 | 아니오 | 05A~05D |

## Priority boundary

P0~P6 의미와 user commitment policy는 All Tomorrow가 소유한다.
실제 execution ordering/preemption mechanics는 00E selected DurableExecutionPort mapping으로 변환한다.

provider/backend queue status나 학교/대회 같은 domain 문자열을 core priority condition으로 사용하지 않는다.

## Report boundary

2026-10-21 상태: **개발중**. Eve가 기존 edge 인증으로 메타인지 보고를 가져가 사용자에게 보내고, Discord 답장을 원래 Event에 연결한다. 가짜 클라이언트 검증 완료, 실제 전달·상시 운영 확인 전이다. [운영 기록](../../dp7-loop.md)의 범위이며 일일 보고 packet 전체 완료를 뜻하지 않는다.

report는 immutable source-backed projection + summary다.

- logical period/timezone identity
- source watermark/version
- late evidence revision
- unknown cost/result 보존
- deterministic fallback

LLM 실패로 report state가 유실되지 않는다.

## 2026-10-21 상태 정정

기존 부품의 존재와 단위시험을 Stage 전체 운영 완료로 표시하지 않는다. [DP7 자기개선 고리](../../dp7-loop.md)에 연결 경로와 남은 검증을 기록했다. 메타인지→영속 Work→사본 실행→시험→반영/되돌림→Event→다음 관측→보고 적재를 연결했다. 실제 DB·Discord·재부팅 검증은 확인 전이다. 서버와 실행기는 DP7, 노트북은 기록 전용이다. 기존 일일 보고 composer나 보호 변경 승인 경계 전체를 완료한 것은 아니다.
