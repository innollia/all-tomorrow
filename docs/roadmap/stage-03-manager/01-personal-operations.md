# Stage 3.1 — Personal Operations

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 2 완료
- 지금 시작 가능: **아니오**

## 목적

school/schedule/task/personal context를 owner-aware adapter로 연결해 actionable Work와 proactive brief를 만들되 중앙 DB가 새 만능 정본이 되지 않게 한다.

## Owner Adapter contract

각 source owner는 최소:

- owner_id
- supported read/query capabilities
- supported mutation capabilities
- canonical record/ref identity
- freshness/version metadata
- access/authority policy
- conflict behavior
- write result/provenance

central system은 owner record 전체를 복제하기보다 logical ref + 필요한 bounded projection을 사용한다.

## Source precedence

같은 사실이 충돌할 때:

1. current explicit user correction/instruction
2. 해당 domain canonical owner
3. accepted cross-project lesson/reference
4. stale cache/derived summary

derived summary가 canonical owner를 overwrite하지 않는다.
conflict가 해소되지 않으면 UNKNOWN/NEED_USER 또는 owner refresh.

## School material pipeline

file/photo/PDF
→ ArtifactRef
→ extraction result ArtifactRef
→ classification/owner resolution
→ source-owner record/ref 또는 bounded projection
→ actionable Goal/Work

필수:

- original artifact hash/provenance
- extraction version/model/tool refs
- page/range/source references
- confidence/unknown regions
- duplicate artifact dedup
- raw document를 Event/telemetry에 복제하지 않음

## Personal query

"뭐 해야 돼?" 같은 질의:

- central open Goal/Work
- owner-provided schedule/tasks/school refs
- pending Questions
- priority/deadline
- freshness

를 ContextPack으로 조립한다.

stale owner state를 current truth처럼 표현하지 않는다.

## Proactive personal brief

brief trigger 자체는 3.2 engine 사용.

brief:

- source timestamps
- due/urgent commitments
- pending Questions
- project/research outcome
- conflicts/unknowns
- explicit source refs

일일 운영 report와 중복 저장소를 만들지 않고 필요한 projection을 재사용한다.

## Requirements

| ID | 요구 | Level |
|---|---|
| 3.1-01 owner adapter read/write provenance | L1 |
| 3.1-02 conflict precedence/unknown handling | L0/L1 |
| 3.1-03 school artifact→actionable Work lineage | L1/L2 |
| 3.1-04 duplicate material dedup | L1 |
| 3.1-05 stale personal state 표시/refresh | L1 |
| 3.1-06 central DB가 owner canonical record를 무차별 복제하지 않음 | architecture |

## 완료조건

personal/school owner truth와 central execution state가 ref/provenance로 연결되고 conflict/freshness가 숨겨지지 않아야 한다.
