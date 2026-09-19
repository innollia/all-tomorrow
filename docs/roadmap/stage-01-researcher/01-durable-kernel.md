# Stage 1.1 — Minimal Semantic Kernel + Durable Execution Bridge

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 완료

이 작업의 목적은 durable workflow engine을 직접 만드는 것이 아니다.

All Tomorrow가 직접 소유하는 Goal/Work 의미를 저장하고, 외부 durable backend에 실행을 맡기는 얇은 경계를 만든다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 01A | Semantic Schema Migration | 선행작업 대기 | 아니오 | Stage 0 | [01a](01-durable-kernel/01a-schema-migration.md) |
| 01B | Goal/Work Domain & Store | 선행작업 대기 | 아니오 | 01A | [01b](01-durable-kernel/01b-domain-and-store.md) |
| 01C | Durable Execution Bridge | 선행작업 대기 | 아니오 | 01B | [01c](01-durable-kernel/01c-durable-queue.md) |
| 01D | Run / Compatibility Linkage | 선행작업 대기 | 아니오 | 01B + 01C | [01d](01-durable-kernel/01d-run-linkage.md) |
| 01E | Live Failure Verification | 선행작업 대기 | 아니오 | 01A~01D | [01e](01-durable-kernel/01e-live-db-verification.md) |

## 더 이상 직접 만들지 않는 것

Stage 0 primary 조합이 통과하는 한 다음은 DBOS에 맡긴다.

- queue claim
- lease/heartbeat
- crash recovery
- retry bookkeeping
- queue priority/delay
- concurrency/rate primitives
- workflow checkpoint
- durable messaging

이 기능을 All Tomorrow schema와 scheduler.py에 다시 구현하지 않는다.

## 완료조건

Goal/Work 의미는 All Tomorrow DB에 남고, 실행 mechanics는 외부 backend가 소유하며, backend process를 죽여도 Work identity와 결과 provenance가 유지된다.
