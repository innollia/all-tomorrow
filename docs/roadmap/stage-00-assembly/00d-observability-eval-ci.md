# 00D — Observability / Eval / CI Seam

## Status

- 상태: **개발중**
- 선행조건: 00C
- 공통 계약:
  - ../plan-verification-contract.md
  - ../domain-contracts.md
  - ../failure-recovery-contract.md
  - ../data-security-artifact-contract.md

## 목적

00C skeleton을 추적·회귀검증·업그레이드 검증할 수 있는 최소 관측/eval/CI rail을 확정한다.

## Observability contract

OpenTelemetry를 공통 propagation/export contract로 사용한다.

필수 correlation:

- goal_id
- work_id
- run_id
- All Tomorrow trace_id
- external execution id
- agent/model span
- worker/tool request/ref
- artifact/result ref when applicable

TracerProvider는 process당 하나다. library별 별도 trace tree를 만든 뒤 Event에 다시 복제하지 않는다.

### Ownership

- PydanticAI: agent/model/tool semantic spans
- durable backend: workflow/invocation/recovery spans
- selected MCP gateway: transport/delegation spans
- All Tomorrow Event: 장기 domain/audit fact

Event에는 모든 span이 아니라 Goal/Work/Run semantic transition, question, authority decision, artifact/proposal 등 장기 fact만 남긴다.

## Privacy defaults

production 기본:

- PydanticAI content/binary/model-request-parameter capture off
- OTel attribute에 raw prompt/tool args/result/secret 금지
- LiteLLM raw prompt/response logging off
- process error log도 secret fixture redaction

debug content capture는 별도 opt-in + retention policy가 있어야 한다.

## Eval dataset

Pydantic Evals를 초기 runner로 사용한다. 각 case는 input fixture, expected decision/property, evidence refs를 가진다.

최소 deterministic contract cases:

| ID | 입력 | 기대 |
|---|---|---|
| E-01 | valid typed decision fixture | schema valid |
| E-02 | unknown evidence ref | reject/no mutation |
| E-03 | tool-required observation | expected tool capability 선택 |
| E-04 | 필수 정보 누락 | NEED_USER/ASK_USER, fabricated answer 금지 |
| E-05 | secret-like content | output/event/telemetry에 secret 없음 |
| E-06 | same request/observation replay | duplicate Work/effect 없음 |
| E-07 | source owner conflict | non-owner overwrite 금지 |
| E-08 | malformed model output | mutation 없음 |

Stage 0 gate:

- E-05/E-06/E-07/E-08은 100% pass 필수
- 나머지도 expected property가 명시된 fixture는 전부 pass해야 함
- 평균 score 하나로 hard contract failure를 상쇄하지 않음
- 미측정 metric은 0으로 채우지 않음

adversarial/red-team 요구가 생기면 Promptfoo를 추가할 수 있으나 초기 필수 dependency는 아니다.

## CI lanes

| Lane | 내용 | 환경 | PR hard gate |
|---|---|---|---|
| unit | pure domain/adapter contract | hosted runner | 예 |
| integration-local | real PostgreSQL + selected local substrate | service/container 또는 reproducible runtime | 예 |
| crash-replay | child process kill/restart + persisted history | Linux runner/self-hosted | substrate 변경 PR은 예 |
| eval | E-01~E-08 + regression data | deterministic model/TestModel + 필요한 integration | 예 |
| architecture | forbidden imports/schema/ownership fitness | hosted runner | 예 |
| security-data | secret/canary/artifact retention negative checks | integration | 예 |
| deployed-smoke | actual AWS/laptop boundary | protected/manual environment | Stage close 및 protected rail 변경 시 필수 |

CI가 환경 제약 때문에 lane을 실행하지 못하면 success로 간주하지 않고 not-run/blocked로 남긴다.

## Architecture fitness checks

최소:

- domain package에서 selected backend internal type import 금지
- Work table 단일 ExecutionRef 금지; Run linkage 사용
- backend system table을 app migration이 소유하지 않음
- raw provider/model object의 domain serialization 금지
- protected credential이 AWS runtime env/config에 없음
- mutable latest image/tag 금지

## Upgrade rail

production substrate는 exact/lockfile pin.

관리 대상:

- Python packages
- durable backend runtime/image/binary
- LiteLLM Proxy
- GitHub Actions
- optional MCP gateway

dependency PR은 최소 다음을 실행한다.

- persisted operation/toolset/name snapshot
- V1 history → candidate replay/drain test
- MCP list/call contract
- model gateway contract
- C-series crash/restart subset
- E-series eval
- secret/canary negative tests

durable history incompatibility가 발견되면 test expectation을 새 버전에 맞춰 덮지 않는다. migration/drain plan이 먼저다.

## Requirements

| ID | 요구 | 증거 |
|---|---|---|
| D-TRACE-01 | skeleton 한 실행을 end-to-end correlation 가능 | trace export + asserted ids |
| D-DUP-01 | 같은 MCP call의 중복 span tree 없음 | span topology assertion |
| D-EVENT-01 | Event row가 span 수에 비례해 폭증하지 않음 | domain-event count fixture |
| D-PRIV-01 | prompt/secret fixture telemetry 검색 결과 0 | negative scan |
| D-EVAL-01 | E-01~E-08 expected property 통과 | eval artifact |
| D-CI-01 | required lanes가 실제 PR check로 실행 | workflow run evidence |
| D-UP-01 | dependency update에서 history compatibility 검증 | replay/drain CI artifact |
| D-RET-01 | recovery payload/log retention inventory 존재 | inventory document/test |

## 완료조건

위 requirement가 모두 evidence로 닫히고, 00C의 실제 failure skeleton이 CI/eval/trace rail에서 재현 가능해야 한다.
