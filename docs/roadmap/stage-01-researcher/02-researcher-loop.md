# Stage 1.2 — Researcher Loop

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01 완료 + Stage 0 agent/model substrate 확정

## Flow

ObservationSnapshot
→ PydanticAI Researcher agent
→ discriminated Typed Decision
→ validated semantic materialization
→ lineage/dedup/budget
→ Run/provenance/outcome

## Ownership

All Tomorrow:

- bounded observation/cursor
- Goal/Work/Question/Proposal materialization
- lineage/dedup/budget
- evidence/source ownership
- metacognition provenance

PydanticAI:

- agent/model/tool interaction mechanics
- typed model validation seam
- MCP/toolset plumbing

canonical DB, source ownership, authority expansion policy는 PydanticAI가 소유하지 않는다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 02A | Observation Snapshot | 선행작업 대기 | 아니오 | 01 |
| 02B | Researcher Agent & Typed Decision | 선행작업 대기 | 아니오 | 02A + 04A |
| 02C | Decision Materialization | 선행작업 대기 | 아니오 | 02B |
| 02D | Lineage / Budget / Dedup | 선행작업 대기 | 아니오 | 02C |
| 02E | Researcher Acceptance | 선행작업 대기 | 아니오 | 02A~02D |

## 금지

- 새 agent framework
- provider별 client branch
- 모든 domain flow를 Pydantic Graph에 강제
- serial meta-agent 하나로 모든 metacognition 강제
- activity/Work 생성량을 autonomous value로 간주
