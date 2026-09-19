# 00A-2 — DBOS Spike

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 00A-1

## 목적

PydanticAI + DBOS 조합이 All Tomorrow의 durable execution 요구를 custom queue/lease/recovery daemon 없이 만족하는지 증명한다.

## 연결 원칙

- DBOS는 durable execution mechanism만 소유
- Goal/Work/Run 의미는 All Tomorrow가 소유
- application DB와 DBOS system state는 논리적으로 분리
- run_id를 deterministic external execution identity 후보로 사용
- domain package는 DBOS 내부 type을 import하지 않음

## PydanticAI Compatibility Check

반드시 확인:

- agent name이 persisted recovery compatibility에 미치는 영향
- toolset/tool/operation 이름 변경이 in-flight execution에 미치는 영향
- DynamicToolset 또는 MCP toolset을 durable하게 쓸 때 stable ID 요구
- runtime-added toolset 제한
- application version upgrade 시 old execution replay/recovery 방법

문서상 가능 여부가 아니라 D10으로 검증한다.

## DBOS-specific Checks

공통 D01~D12 외에 기록:

- workflow-ID duplicate behavior
- queue priority/delay mapping 가능 범위
- concurrency/rate-control을 custom scheduler 없이 표현 가능한 범위
- durable signal/message mapping
- single-node에서 필요한 별도 process 수
- Postgres/SQLite system DB 선택의 운영 차이
- multi-host로 갈 때 Conductor가 필요한 시점과 현재 license boundary

## Durable Data Footprint

unique canary를 model input, tool input, tool output에 각각 넣고 다음에서 검색한다.

- application DB
- DBOS system DB
- stdout/stderr
- OTel export
- LiteLLM logs if model gateway를 붙인 추가 실험을 했다면 해당 로그

workflow input/output, step output, serializer 형식, retention/cleanup, backup/encryption 경계를 기록한다.

## 탈락 조건

- D01~D12 hard scenario 중 필수 항목 실패
- ordinary upgrade마다 in-flight execution을 버려야 함
- Goal/Work schema가 DBOS workflow schema에 종속
- external mutation duplicate를 제어할 seam 없음
- personal AWS single-node에서 과도한 상시 control plane 필요

## 산출물

- exact version
- setup steps
- adapter/glue LOC
- D01~D12 결과
- data-footprint 결과
- 운영/라이선스 제약
- DBOS를 제거할 때 유지되는 All Tomorrow contract
