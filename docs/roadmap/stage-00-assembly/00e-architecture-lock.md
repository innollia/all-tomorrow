# 00E — Architecture Lock & Stage 1 Rewrite

## Status

- 상태: **선행작업 대기**
- 선행조건: 00A~00D

## 목적

spike 결과로만 Stage 1을 다시 연다.

## 해야 할 일

- 채택한 durable substrate와 exact version pin 기록
- LiteLLM MCP Gateway 채택 결과 기록
- FastMCP fallback 필요 여부 기록
- 각 substrate consumption mode(package/container/protocol/fork) 기록
- backend 교체 조건 기록
- durable journal data-classification/retention/backup 정책 기록
- LiteLLM persistence/logging on/off 결정 기록
- architecture/ADR를 실제 결과에 맞게 갱신
- Stage 1 schema에서 substrate 내부 상태 제거
- custom queue/lease/heartbeat 계획 삭제
- LiteLLM raw client 계획을 실제 PydanticAI integration에 맞게 축소
- 기존 PipelineRuntime의 지위를 유지/compatibility/retire 중 하나로 결정
- Stage 1 acceptance를 crash/restart/versioning 중심으로 갱신

## Durable Backend별 특별 확인

### DBOS 채택 시

DBOS application version과 in-flight workflow recovery 관계를 배포 계획에 넣는다.

DBOS Python 기본 serializer가 pickle+Base64이고 workflow input/output/step output이 system DB에 남는다는 점을 데이터 분류에 포함한다. custom serializer/encryption을 사용할 경우 DBOS tooling/recovery와 round-trip compatibility를 acceptance에서 검증한다.
Conductor 없이 single-node production을 시작하는 경우 그 선택을 명시하고, Conductor 기능에 암묵적으로 의존하는 운영 절차를 쓰지 않는다.

초기 single-node AWS에서는 Conductor 없이 사용할 수 있지만, multi-host/high-availability가 필요해질 때는:
- DBOS Conductor의 운영/라이선스 조건을 재검토하거나
- PydanticAI native 지원인 Temporal로 migration spike
- Hatchet은 embedded/self-host 장점이 native-agent integration 비용보다 큰지 별도 비교

를 수행한다.

### Restate 채택 시

- BSL 1.1의 Public Restate Platform Service 제한과 All Tomorrow 사용 형태가 충돌하지 않는지 기록
- journal/state에 저장되는 serialized payload의 data classification/retention
- runtime single-node backup/restore
- application PostgreSQL과 Restate state의 ownership 중복 여부
- service/virtual-object/workflow 중 All Tomorrow에 필요한 최소 primitive
- deployment version 변경 중 invocation recovery
- Pydantic integration upgrade compatibility

## Persisted Compatibility 확인

PydanticAI/DBOS가 durable history에 사용하는 agent name, toolset id, durable operation/step name은 compatibility data로 취급한다.

일반적인 tool 추가가 기존 workflow를 깨지 않도록 stable MCP/DynamicToolset 경계를 선택하고 versioning/upgrade 문서에 남긴다.

## 완료조건

Stage 1의 각 packet이 "직접 구현할 의미"와 "외부 OSS에 맡길 mechanism"을 섞지 않고, 01A를 실제로 시작해도 되는 상태가 된다.
