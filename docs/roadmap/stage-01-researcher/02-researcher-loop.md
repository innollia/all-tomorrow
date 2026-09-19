# Stage 1.2 — Researcher Loop

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01 Durable Kernel 완료
- 실제 model-driven wake 추가 조건: 04A LiteLLM Gateway

이 파일은 02 작업의 local index다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 02A | Observation Snapshot | 선행작업 대기 | 아니오 | 01 완료 | [02a](02-researcher-loop/02a-observation-snapshot.md) |
| 02B | Researcher Wake & Decision | 선행작업 대기 | 아니오 | 02A + 04A | [02b](02-researcher-loop/02b-researcher-wake.md) |
| 02C | Decision Materialization | 선행작업 대기 | 아니오 | 02B | [02c](02-researcher-loop/02c-materialization.md) |
| 02D | Lineage / Dedup / Budget | 선행작업 대기 | 아니오 | 02C | [02d](02-researcher-loop/02d-lineage-dedup-budget.md) |
| 02E | Researcher Acceptance | 선행작업 대기 | 아니오 | 02A~02D | [02e](02-researcher-loop/02e-acceptance.md) |

## 핵심 구조

Observation → Wake → typed Decision → durable Materialization → lineage/budget/dedup.

별도 meta-meta 계층이나 problem taxonomy를 만들지 않는다.
