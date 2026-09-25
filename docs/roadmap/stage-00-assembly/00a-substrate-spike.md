# 00A — Substrate Spike & Selection

## Status

- 상태: **개발완료**
- 지금 시작 가능: **예**
- 선행조건: 없음
- 완료조건: 선택 중심 범위의 00A-1~00A-5 완료 (2026-09-20 사용자 지시)

## 목적

한 문서에서 모든 후보를 동시에 다루지 않는다.

00A는 아래 의존 관계대로 작은 실험을 수행해 durable backend와 tool gateway를 **서로 독립적으로** 검증한 뒤 마지막에 조합을 잠근다.

## Subpackets

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 파일 |
|---:|---|---|---:|---|---|
| 00A-1 | Common Harness | 개발완료 | — | 없음 | [00a-1](00a-1-common-harness.md) |
| 00A-2 | DBOS Spike | 개발완료 | — | 00A-1 | [00a-2](00a-2-dbos-spike.md) |
| 00A-3 | Restate Spike | 개발완료 | — | 00A-1 | [00a-3](00a-3-restate-spike.md) |
| 00A-4 | Tool Gateway Spike | 개발완료 | — | 00A-1 | [00a-4](00a-4-gateway-spike.md) |
| 00A-5 | Selection Record | 개발완료 | — | 00A-2~00A-4 | [00a-5](00a-5-selection.md) |

00A-1 이후 00A-2/3/4는 독립적으로 진행할 수 있다. 00A-5만 셋 모두를 기다린다.

2026-09-20: [검증 범위를 후보 선택에 맞춰 축소](00a-live-gate-matrix.md)하고 **DBOS + LiteLLM을 선택**했다. 실제 결합 흐름이 통과했으며 [최종 선택·운영 계약](00a-5-selection.md)을 기준으로 00B를 시작할 수 있다. 과거 감사 기록은 역사적 기록으로 보존한다.

## 결정 축 분리

00A에는 서로 다른 두 결정이 있다.

1. **Durable backend** — DBOS vs Restate
2. **Tool gateway** — LiteLLM MCP Gateway vs 필요 시 FastMCP fallback

LiteLLM MCP Gateway 실패 때문에 DBOS/Restate가 탈락하거나, durable backend 문제 때문에 gateway가 탈락하는 식으로 평가 축을 섞지 않는다.

00A-5에서 선택된 durable backend와 gateway의 실제 사용 흐름을 확인했다. 모든 장애 조합의 재인증은 완료조건에서 제외했다.

## 공통 기반

- PydanticAI
- LiteLLM Proxy model gateway
- OpenTelemetry
- 실제 PostgreSQL where needed
- Python 3.13
- personal AWS single-node를 첫 production target으로 가정

## Research Snapshot — 2026-09-19

현재 조사 시점의 후보는 다음과 같다.

| substrate | snapshot |
|---|---|
| PydanticAI | 2.46.0 |
| DBOS Python | 3.0.0 |
| Restate Python SDK | 1.0.5 |
| Restate runtime | 1.7.10 |
| FastMCP | 4.0.5 |
| LiteLLM | 1.101.0 |

이 표는 비교에 사용한 버전이다. 선택한 production pin은 00A-5 및 root lockfile을 따른다.

## 공통 원칙

- 두 durable finalist를 production dependency에 동시에 남기지 않는다.
- package/container/protocol로 소비하고 source vendoring/fork는 마지막 수단으로 둔다.
- 한 failure class의 retry owner는 하나만 둔다.
- durable journal은 trusted sensitive store로 취급한다.
- Goal/Work와 application domain state는 backend 내부 schema와 분리한다.
- Event를 trace archive로 만들지 않는다.
- 실험 결과 없이 framework를 추가하지 않는다.

## 완료조건

00A-5에 다음이 기록되면 완료다.

- durable backend 채택 또는 둘 다 기각
- tool gateway 채택 또는 fallback 채택
- 사용한 exact versions
- 통과/실패 scenario
- glue/adapter LOC
- persistent process/state-system 수
- privacy/data footprint
- upgrade/recovery 결과
- 우리가 직접 쓰지 않게 된 코드
- 새로 떠안은 운영 책임
- migration trigger
