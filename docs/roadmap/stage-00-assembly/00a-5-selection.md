# 00A-5 — Selection Record

## Status

- 상태: **개발완료**
- 결정일: 2026-09-20
- 후속: **00B 시작 가능**
- 기준: 사용자가 승인한 [선택 중심의 축소 범위](00a-live-gate-matrix.md)

## 결정과 대안

**Durable backend는 DBOS 3.0.0, model/tool gateway는 LiteLLM Proxy 1.101.0을 선택한다.** Agent는 PydanticAI 2.46.0이다.

DBOS와 Restate 모두 필요한 기본 durable 의미론과 typed agent 연결을 확인했다. Restate를 신뢰성이나 설치 실패로 탈락시키지 않는다. 현재 목표는 Python 3.13·단일 노드·PostgreSQL 기반이며, DBOS는 이미 필요한 DB를 이용해 별도 durable 서버와 journal 저장소를 추가하지 않는다. 두 후보의 기능이 충분한 상황에서 이 운영 단순성이 결정적이다.

LiteLLM은 예정된 model gateway와 MCP gateway를 한 운영 단위로 제공한다. 실제 PydanticAI 연결, namespace, discovery, access filter와 privacy 설정에 구조적 장애가 없었다. 별도 FastMCP gateway를 추가할 이유가 없어 fallback을 사용하지 않는다. 두 route가 같은 프로세스 장애 영역을 공유하는 비용은 수용한다.

## 직접 확인한 실제 흐름

`tests/test_combined_gateway_agent.py::test_agent_through_model_and_tool_gateway[durable_crash]`가 최종 통과했다. 결과: `.artifacts/00a/selection-flow.xml` (2026-09-20, 실패/skip 없음).

PydanticAI → 실제 LiteLLM model endpoint → 실제 MCP gateway/upstream 호출 → DBOS step 결과 → 외부 mutation → commit 직후 worker 종료 → 새 worker의 idempotent 복구 → 승인 대기 → signal → 완료를 확인했다. 외부 fixture는 호출 2회·적용 1회이며, 같은 실행 결과와 원래 trace가 유지되고 비공개 입력/키는 로그·span에 없었다.

모델 provider는 결정적 OpenAI wire fixture다. 이 시험은 SDK/HTTP/MCP/durable 경계의 결합 가능성을 확인하며 외부 모델의 품질, rate limit 또는 가용성을 보증하지 않는다. 양쪽 후보의 TestModel 공통 흐름, 모델 replay, 중복 ID, Work/Run 분리, 기본 timer/cancel 및 upgrade 증거는 [분류표](00a-live-gate-matrix.md)를 참조한다. 이미 얻은 증거를 다시 시험하지 않았다.

## 구성과 구현 비용

공통 model/tool gateway와 upstream은 비교에서 제외한 증분이다.

| 항목 | DBOS | Restate |
|---|---|---|
| durable 실행 구성 | Python worker + PostgreSQL | Python handler + Restate 서버 + application PostgreSQL |
| 상태 시스템 | PostgreSQL 1종, domain/system DB 논리 분리 | PostgreSQL + Restate journal 2종 |
| 별도 durable 서버 | 없음 | 1개 |
| spike worker 물리 LOC | 157 | 96 |
| 공통 support | 공유 fixture/model/trace helper 78줄, process 제어 137줄 | 동일 |

LOC는 2026-09-20 시험용 코드의 주석·공백 포함 값이며 production adapter 추정치가 아니다. DBOS가 항상 코드가 더 짧다는 주장은 하지 않는다. 테스트 제어 코드를 더 추상화해 점수를 개선하는 작업도 하지 않는다. 별도 runtime 등록/배포·저장소 운영을 피하는 것이 현 시점의 이점이다.

## 00B에 넘기는 계약

- All Tomorrow는 Goal/Work/Run, 권한, provenance, 정책 및 외부 effect의 의미를 소유한다. DBOS는 실행/step journal·wait/timer/recovery를 소유한다.
- 외부 실행 ID는 `work_id:run_id`. 같은 Run 재시도는 동일 ID, 새 의미적 시도는 새 Run이다. production ID 형식과 포트는 00B에서 확정한다.
- mutation의 idempotency key는 논리 effect에 고정한다. 중단 후 결과가 불명확하면 외부 store에서 결과를 조회/재사용한다. DBOS replay만으로 외부 효과 exactly-once를 주장하지 않는다.
- 모델 실행을 하나의 durable step으로 경계 지었다. 저장 전 중단은 모델을 다시 호출할 수 있고, 저장 후에는 결정을 재사용한다. 더 세밀한 agent 내부 checkpoint가 필요한 경우에만 native durability wrapper를 별도로 평가한다.
- wait/signal payload와 모델 결정은 typed 값으로 넘긴다. DBOS 내부 type/schema가 domain에 새지 않게 adapter에서 변환한다.
- workflow/step 및 MCP toolset ID는 persisted contract다. `all-tomorrow-tools`와 tool 정의 fingerprint를 Run 시작에 기록한다. 동적 discovery는 새 Run에서 수행한다.
- 호환 가능한 app/dependency 변경은 같은 compatibility version으로 replay한다. 단계 순서/이름·입출력의 비호환 변경은 새 버전으로 분리하고 기존 worker를 유지해 drain한다. PydanticAI 2.45.0→2.46.0 및 V2 finalization은 양쪽 시험에서 복구했다.

## Retry 책임

| 층 | 관측/설정 | 책임 |
|---|---|---|
| OpenAI SDK | 설치 SDK 기본 2; 결합 client `max_retries=0` | 전송 재시도 비활성 |
| LiteLLM | 결합 router/provider `num_retries=0`, fallback 없음 | 중첩 재시도 비활성 |
| PydanticAI | 기본/설정 validation retry 1, MCP tool retry 0 | 출력 검증 교정만 |
| DBOS model step | exception retry 기본 off; probe는 transient predicate, 최대 6 attempts, 2초 간격 | 연결 오류/지정 HTTP transient error의 유일한 자동 retry owner |
| All Tomorrow | 자동 semantic retry 0 | 정책상 재시도는 새 Run으로 명시 |

숫자는 실제 코드에 있는 설정이다. 장애별 재시도 횟수의 전면 검증이나 production backoff 튜닝은 하지 않았다. Restate의 retry 정책을 DBOS와 같은 숫자로 일반화하지 않는다. `retry_matrix.py`는 책임 모델이며 클라이언트 설정 적용 자체를 대체하지 않는다.

## 데이터와 운영 책임

- Journal은 입력·결정·step 결과를 보관하는 **trusted sensitive store**다. DBOS 입력 카나리를 base64 pickle에서 확인했다. 인코딩은 암호화가 아니다.
- 최소 typed 입력과 artifact 참조를 사용하고 provider key/불필요한 원문은 journal에 전달하지 않는다. DBOS system DB와 domain DB는 별도 database/schema·권한 경계를 둔다.
- 개인 AWS 배포 시 저장 볼륨/백업 암호화, 접근 제한과 TLS는 운영자가 구성한다. 이 spike는 실제 AWS 배포·암호화·복구 SLA를 인증하지 않았다.
- 완료 journal 보존 목표는 7일, active/waiting 실행은 만료 삭제하지 않는다. 정리 전에 domain 결과와 외부 idempotency 조회를 유지한다. SDK 삭제 API를 통한 보존 작업과 암호화된 PostgreSQL 백업/복원 절차는 실제 운영 배포에서 구현한다. 임의 SQL로 backend 내부 표를 삭제하지 않는다.
- 초기 백업은 PostgreSQL domain/system DB 모두를 대상으로 하며, 복원 시 외부 effect와 재조정한다. 외부 효과는 DB 복원으로 되돌아가지 않는다.
- OTel은 `include_content=False`, IDs와 상태 중심으로 수집한다. LiteLLM은 callbacks off, prompt/spend/message 원문 수집 off, runtime env credential을 사용한다. gateway DB/virtual keys는 현재 도입하지 않는다.
- Restate를 선택한다면 별도 journal 상태·설정의 백업/보존·네트워크 경계를 추가 운영해야 한다. 이 차이는 선택 비용으로 반영했으며 제품 결함은 아니다.

근거: [DBOS version/recovery 설명](https://docs.dbos.dev/python/prompting), [DBOS architecture](https://docs.dbos.dev/architecture), [Restate backup 단위](https://docs.restate.dev/server/snapshots), [Restate retention/retry 설정](https://docs.restate.dev/services/configuration). 구체적 동작 판정은 위 설치 버전의 실행 증거를 우선한다.

## 버전과 upgrade 통제

- root production: `pyproject.toml`의 DBOS 3.0.0 / PydanticAI 2.46.0 / OTel SDK 1.44.0, `uv.lock`.
- separate gateway: `deploy/gateway/requirements.txt`의 LiteLLM Proxy 1.101.0. 별도 환경으로 dependency graph 충돌을 격리한다.
- Restate SDK 1.0.5 / server 1.7.10 / FastMCP fixture 4.0.5는 비교 실험 버전이며 production durable dependency로 추가하지 않는다.
- 아직 container 배포를 채택하지 않아 image pin을 만들지 않았다. 향후 배포 시 digest를 고정하고 mutable latest를 사용하지 않는다.
- Dependabot은 root와 gateway에 PR을 제안하도록 설정했다. 자동 merge workflow는 만들지 않았다. substrate upgrade는 관련 사용 흐름/contract 변화의 검토와 수동 merge를 요구하며, 전체 장애 조합 인증을 요구하지 않는다.

## 직접 만들지 않을 것 / 재검토 조건

custom durable queue, lease/heartbeat, recovery daemon, 별도 agent framework, model SDK client 재구현을 추가하지 않는다. 이번 선택은 기존 사용자 기능 삭제나 00B adapter 구현 완료를 의미하지 않는다.

다중 호스트 운영이 현재 DBOS 구성보다 복잡해지거나 Restate 고유한 keyed service/배포 모델이 필요한 경우 durable 선택을 재검토한다. gateway의 필수 MCP 계약이 깨지거나 model/tool 장애 영역 분리가 실제 요구가 되면 FastMCP 또는 분리 프로세스를 평가한다. 일반적인 upstream 업데이트나 미실행 장애 조합만으로 후보 재평가를 열지 않는다.

## 완료 판정

선택을 바꾸는 불확실성과 직접 의존하는 의미론을 확인했고, 필요한 전체 사용 흐름이 통과했다. 사용자 승인으로 제외한 upstream 재인증/선택 무관 작업은 gate가 아니다. **00A 완료, 00B 시작 가능.** Stage 0 전체는 00B~00E가 남아 있으므로 개발중이다.
