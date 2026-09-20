# 02D — Autonomous Lineage, Dedup and Budget

## Status

- 상태: **선행작업 대기**
- 선행조건: 02C 완료
- 지금 시작 가능: **아니오**
- 완료 후 열림: 02E

## 목적

임의 depth 제한 없이 autonomous recursion/work storm을 DB-enforced dedup과 resource accounting으로 제한한다.

## Lineage

researcher-created Goal/Work:

- origin
- root_autonomous_lineage_id
- parent Goal/Work optional
- source_snapshot_id
- decision_id
- evidence refs
- created_at

## Dedup fingerprint

fingerprint_version을 포함한 canonical input:

- action type
- target Goal/project IDs
- normalized objective semantic key
- sorted stable evidence ref IDs
- relevant target ID
- materializer schema version

자유 title 문장 전체를 그대로 hash하지 않는다. normalization은 versioned function이며 변경 시 기존 fingerprint와 충돌/재처리 정책을 명시한다.

DB에 open-autonomous-work dedup key를 unique partial constraint 또는 동등한 transaction-safe constraint로 둔다.
"먼저 조회 후 insert"만으로 race를 막지 않는다.

## Budget ledger

lineage budget dimensions:

- max created Work
- model token/cost
- wall-clock age
- max concurrent active Run
- optional executor/resource quota

budget config는 version/ref를 가진다.

### Accounting semantics

- Work-count: Work 생성 transaction에서 reserve/consume
- concurrency: Run 시작 전 slot reserve, terminal/cancel 시 release
- token/cost: known usage 발생 시 actual consume; 실행 전에는 policy-defined estimated reservation 가능
- unknown actual cost: 0으로 정산하지 않고 UNKNOWN usage로 남겨 추가 autonomous spending을 fail-closed 또는 configured conservative rule로 제한
- failed call도 provider cost가 발생했으면 consume
- cancellation이 이미 발생한 cost를 refund하지 않음
- wall-clock age는 lineage created_at 기준이며 reset하지 않음
- budget revision이 바뀌어도 과거 usage는 유지

budget reserve/consume은 DB transaction/CAS로 concurrent overcommit을 막는다.

## Wake concurrency

02A short DB lock + cursor CAS를 사용한다. 별도 durable lease subsystem을 만들지 않는다.
materialization dedup constraint가 마지막 방어선이다.

## Requirements

| ID | 요구 | 검증 | Level |
|---|---|---|---|
| 02D-01 | concurrent same decision → Work 1개 | concurrent DB test | L1 |
| 02D-02 | wording variation이 canonical key 동일 시 dedup | normalization fixture | L0 |
| 02D-03 | different stable evidence/context면 별도 Work 허용 | unit/integration | L0/L1 |
| 02D-04 | concurrent budget reservation이 ceiling 초과 안 함 | concurrent DB test | L1 |
| 02D-05 | unknown cost를 0으로 처리하지 않음 | negative test | L0 |
| 02D-06 | deep lineage도 budget 내면 허용 | property test | L0 |
| 02D-07 | budget exhaustion이 기존 state 삭제하지 않음 | integration | L1 |

## 완료조건

dedup과 budget이 application-level 선조회가 아니라 transaction/constraint 수준에서 race-safe하며 autonomous work가 resource ceiling 안에서 유한해야 한다.
