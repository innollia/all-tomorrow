# 00A — Substrate Spike & Selection

## Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 없음

## 목적

문서 비교가 아니라 같은 walking-skeleton을 여러 OSS 조합에 짧게 연결해 glue 비용과 실패 경계를 비교한다.

## 공통 조각

- PydanticAI
- LiteLLM Proxy
- OpenTelemetry
- FastMCP tool gateway candidate
- 실제 PostgreSQL where needed

## Durable Finalists

### A. DBOS

검증 이유:
- PydanticAI native durable capability
- Python library로 시작 가능
- Postgres system database
- workflow ID idempotency
- queue priority/delay/concurrency/rate primitives
- durable messaging
- single-node에서는 별도 control server 없이 시작 가능

주의:
- distributed/HA 운영에서 Conductor가 필요해질 수 있음
- self-hosted production Conductor는 현재 별도 라이선스 조건이 있음
- PydanticAI agent/toolset/operation의 persisted names가 recovery compatibility data

### B. Restate

검증 이유:
- PydanticAI integration
- self-host runtime이 single binary
- durable steps + signals/promises + keyed state + RPC + queues/flow control
- waiting 동안 compute를 붙잡지 않는 long-running/HITL 모델
- 별도 PostgreSQL을 durable engine 자체가 요구하지 않음

주의:
- All Tomorrow가 이미 application PostgreSQL을 가지므로 state system이 하나 더 생김
- Restate runtime은 SDK와 다른 라이선스 경계를 가짐
- Pydantic integration의 tool/model wrapping 동작과 upgrade contract를 실제로 확인해야 함

## Secondary Candidates

Primary 두 조합이 acceptance를 닫지 못할 때만 더 깊게 판다.

- Temporal: PydanticAI native. 강한 versioning/recovery, 운영 중량 큼.
- Hatchet: MIT/self-host/embedded/Postgres/UI 강점. PydanticAI durable backend builder를 쓰는 custom integration 비용 측정 필요.
- Prefect: PydanticAI native/Apache 2.0. 초기 personal control-plane보다 넓은 orchestration surface가 필요한지 확인.

## Stable Tool Gateway Spike

agent에는 매번 새 MCPToolset을 꽂지 않는다.

후보 구조:

PydanticAI Agent
→ 하나의 stable MCPToolset id: `all-tomorrow-tools`
→ FastMCP gateway
→ Eve / GitHub / filesystem / custom MCP / HTTP-backed tools

검증:
- backend tool 추가 후 **새 run**의 list_tools에 반영
- in-flight durable run은 자신의 기록된 discovery/definition과 모순 없이 recovery
- namespace collision 방지
- allow/deny/filter 가능
- gateway failure가 agent durability와 어떻게 상호작용하는지 확인
- raw credential이 agent/work payload에 들어가지 않음

FastMCP의 ProxyProvider/mount/composition으로 충분하면 자체 gateway를 만들지 않는다.

## 조립 순서

한 번에 전체 stack을 띄우지 않는다.

1. **Durability only**
   - PydanticAI TestModel 또는 local deterministic model
   - DBOS spike
   - Restate spike
   - 동일 crash/idempotency/HITL acceptance
2. **Tool seam**
   - winner 위에 stable FastMCP gateway 하나만 추가
   - 실제 upstream MCP 2개 이상 proxy/mount
   - tool discovery/recovery 확인
3. **Model gateway**
   - local/OpenAI-compatible stub을 LiteLLM Proxy로 교체
   - routing/cost/error normalization 확인
4. **Telemetry**
   - 하나의 OTel provider/exporter 연결
   - duplicate span/privacy 확인
5. **CI/eval**
   - 같은 skeleton을 regression으로 고정

각 단계가 깨지면 직전 단계가 통과한 상태에서 원인을 좁힌다.

## Same Acceptance For Both Durable Finalists

각 finalist에 정확히 같은 scenario를 실행한다.

1. model call
2. MCP/FastMCP gateway tool discovery
3. tool call
4. process kill/restart
5. duplicate start
6. user wait/signal/resume
7. priority 또는 flow-control equivalent
8. long delay/timer
9. external side effect 직후 crash
10. application version upgrade 중 old execution recovery
11. OTel correlation
12. execution cancel
13. backend unavailable/reconnect
14. dynamic gateway tool addition 후 new run discovery

## Selection Metrics

숫자로 기록:
- glue LOC
- custom adapter LOC
- 별도 daemon/process 수
- persistent state systems 수
- cold-start/setup steps
- failure scenarios passed
- version-upgrade ceremony
- license/production constraints
- tool/MCP compatibility gaps
- observability duplication
- AWS idle footprint

기능 수가 많은 쪽이 아니라 **All Tomorrow가 직접 유지할 코드와 운영 상태가 적은 쪽**을 고른다.

## Retry Ownership Check

각 조합에서 동일 요청이 다음 층에서 몇 번 재시도될 수 있는지 기록한다.

- provider SDK
- LiteLLM
- PydanticAI
- durable engine
- All Tomorrow Work retry

retry multiplication이 생기면 한 failure class당 한 주된 retry owner만 남긴다.

## 즉시 탈락 조건

- Goal/Work domain을 backend workflow schema에 맞춰 왜곡해야 함
- raw provider credential을 durable payload에 넣어야 함
- 외부 mutation의 duplicate side effect를 다룰 seam이 없음
- stable MCP gateway 뒤의 tool 추가조차 agent code 재작성/재배포를 계속 요구
- in-flight execution recovery가 ordinary dependency update마다 쉽게 깨짐
- single-node 개인 AWS에서 요구 이상의 상시 infra가 필수

## Dependency Consumption Rule

외부 프로젝트를 "가져온다"는 말은 source를 repo 안에 복붙한다는 뜻이 아니다.

우선순위:
1. Python/package dependency
2. pinned container/binary
3. stable HTTP/MCP protocol
4. upstream fork는 필요한 patch가 실제로 증명될 때만

초기에는 git submodule, vendored source copy, 장기 private fork를 만들지 않는다. fork가 필요해지면 patch 크기와 upstream merge 가능성을 별도 비용으로 기록한다.

## License Notes

- PydanticAI: MIT
- DBOS Transact Python: MIT
- FastMCP: Apache-2.0
- Restate Python SDK: MIT
- Restate runtime: BSL 1.1; 자체 production 사용은 허용되지만 Public Restate Platform Service 제한을 유지
- DBOS Conductor: self-hosted production은 별도 proprietary license

Stage 0의 개인용 single-node 선택과 향후 public/multi-user service 선택을 같은 라이선스 판단으로 뭉개지 않는다.

## 완료조건

DBOS/Restate spike 결과표가 있고 하나를 채택하거나 둘 다 기각한다.

선택 결과에는 "왜 다른 후보가 졌는지"보다 다음을 반드시 남긴다.
- 우리가 직접 쓰지 않게 된 코드
- 새로 떠안은 운영 책임
- migration trigger
- pinned versions
