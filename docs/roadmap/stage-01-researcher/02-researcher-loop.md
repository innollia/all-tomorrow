# Stage 1.2 — Researcher Loop

## Status

- 상태: **개발중**
- 지금 시작 가능: **예**
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
| 02A | Observation Snapshot | 개발중 | 아니오 | 01 |
| 02B | Researcher Agent & Typed Decision | 개발중 | 아니오 | 02A + 04A |
| 02C | Decision Materialization | 개발중 | 아니오 | 02B |
| 02D | Lineage / Budget / Dedup | 개발중 | 아니오 | 02C |
| 02E | Researcher Acceptance | 개발중 | 아니오 | 02A~02D |

## 금지

- 새 agent framework
- provider별 client branch
- 모든 domain flow를 Pydantic Graph에 강제
- serial meta-agent 하나로 모든 metacognition 강제
- activity/Work 생성량을 autonomous value로 간주

## 2026-10-21 상태 정정

기존 부품의 존재와 단위시험을 Stage 전체 운영 완료로 표시하지 않는다. [DP7 자기개선 고리](../../dp7-loop.md)에 연결 경로와 남은 검증을 기록했다. 메타인지→영속 Work→사본 실행→시험→반영/되돌림→Event→다음 관측→보고 적재를 연결했다. 실제 DB·Discord·재부팅 검증은 확인 전이다. 서버와 실행기는 DP7, 노트북은 기록 전용이다. 기존 일일 보고 composer나 보호 변경 승인 경계 전체를 완료한 것은 아니다.
