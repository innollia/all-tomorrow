# Stage 1.2 — Researcher Loop

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01 완료 + Stage 0에서 agent/model substrate 확정

이 파일은 02 작업의 local index다. 하위 packet 세부는 Stage 0 완료 시 최종 조정한다.

## 구현 방향

Observation
→ PydanticAI Researcher agent
→ typed Decision
→ All Tomorrow semantic materialization
→ durable execution/provenance

PydanticAI가 agent/model/tool/MCP plumbing을 담당한다.

All Tomorrow가 소유:
- observation snapshot 구성
- 어떤 Goal/Work를 생성할지의 domain materialization
- lineage/budget/dedup의 사용자 의미
- metacognition provenance

PydanticAI가 소유하지 않는 것:
- canonical Goal/Work DB
- project source ownership
- authority expansion policy

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 02A | Observation Snapshot | 선행작업 대기 | 아니오 | 01 |
| 02B | Researcher Agent & Typed Decision | 선행작업 대기 | 아니오 | 02A + model wiring |
| 02C | Decision Materialization | 선행작업 대기 | 아니오 | 02B |
| 02D | Lineage / Budget / Dedup | 선행작업 대기 | 아니오 | 02C |
| 02E | Researcher Failure Acceptance | 선행작업 대기 | 아니오 | 02A~02D |

## 하지 말 것

- 새 agent framework 작성
- provider별 model client 작성
- Pydantic Graph를 쓴다는 이유로 모든 domain flow를 graph node로 변환
- 메타인지 전체를 하나의 serial agent graph로 강제
