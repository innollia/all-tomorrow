# Stage 1.1 — Minimal Semantic Kernel + Durable Execution Bridge

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 완료
- 공통 계약: ../domain-contracts.md, ../failure-recovery-contract.md, ../plan-verification-contract.md

이 작업은 durable workflow engine을 직접 만드는 것이 아니다.
All Tomorrow가 소유하는 Goal/Work/Run 의미를 저장하고 Stage 0에서 선택·검증된 durable backend에 실행 mechanics를 맡긴다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 01A | Semantic Schema Migration | 선행작업 대기 | 아니오 | Stage 0 | [01a](01-durable-kernel/01a-schema-migration.md) |
| 01B | Goal/Work/Run Domain & Store | 선행작업 대기 | 아니오 | 01A | [01b](01-durable-kernel/01b-domain-and-store.md) |
| 01C | Durable Execution Bridge | 선행작업 대기 | 아니오 | 01B + 00E mapping | [01c](01-durable-kernel/01c-durable-execution-bridge.md) |
| 01D | Run / Compatibility Linkage | 선행작업 대기 | 아니오 | 01B + 01C | [01d](01-durable-kernel/01d-run-linkage.md) |
| 01E | Live Failure Verification | 선행작업 대기 | 아니오 | 01A~01D | [01e](01-durable-kernel/01e-live-db-verification.md) |

## All Tomorrow가 직접 만들지 않는 mechanics

selected durable backend가 00A~00E에서 acceptance를 통과한 범위:

- queue claim
- lease/heartbeat
- process crash recovery
- durable retry bookkeeping
- execution priority/delay mechanics
- concurrency/rate primitives
- workflow checkpoint/journal
- durable signal/message/wait

이를 application schema/scheduler에 다시 구현하지 않는다.

## Stage exit

- Goal/Work/Run 의미는 application DB에서 backend 독립적으로 설명 가능
- ExecutionRef는 Run에만 연결
- external execution mechanics는 selected backend 소유
- process kill/restart와 cross-store crash에서도 same semantic identity/provenance 유지
- backend escape contract test 통과
