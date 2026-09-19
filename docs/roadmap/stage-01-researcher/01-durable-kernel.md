# Stage 1.1 — Minimal Durable Kernel

## Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 없음
- 다음으로 여는 작업: Researcher Loop

이 파일은 구현 상세가 아니라 **01 작업의 상태 인덱스**다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 01A | Schema Migration | 시작안했음 | 예 | 없음 | [01a-schema-migration.md](01-durable-kernel/01a-schema-migration.md) |
| 01B | Goal/Work Domain & Store | 선행작업 대기 | 아니오 | 01A | [01b-domain-and-store.md](01-durable-kernel/01b-domain-and-store.md) |
| 01C | Durable Queue & Lease | 선행작업 대기 | 아니오 | 01A + 01B | [01c-durable-queue.md](01-durable-kernel/01c-durable-queue.md) |
| 01D | Work ↔ Run Linkage | 선행작업 대기 | 아니오 | 01B | [01d-run-linkage.md](01-durable-kernel/01d-run-linkage.md) |
| 01E | Live PostgreSQL Verification | 선행작업 대기 | 아니오 | 01A~01D | [01e-live-db-verification.md](01-durable-kernel/01e-live-db-verification.md) |

## 병렬 가능성

01B 완료 후:

- 01C Durable Queue
- 01D Run Linkage

는 병렬 진행 가능.

01E는 둘 다 끝난 뒤 수행.

## 읽기 규칙

실제 구현자는 이 파일 + 현재 packet 하나만 먼저 읽는다.

추가 문서는 packet의 `Read with` 또는 수정 대상 코드가 요구할 때만 연다.

## Stage 1.1 완료조건

01A~01E가 모두 개발완료이고 live PostgreSQL acceptance가 통과하면:

- 이 파일 상태 → 개발완료
- Stage 1 index의 Minimal Durable Kernel → 개발완료
- Researcher Loop → 시작안했음 / 지금 시작 가능=예
