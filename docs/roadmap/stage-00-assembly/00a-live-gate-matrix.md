# 00A 검증 분류와 범위 조정 — 2026-09-20

사용자의 2026-09-20 지시에 따라 00A 완료 기준을 재설정했다. DBOS와 Restate가 성숙한 upstream이라는 전제 아래, 우리 프로젝트의 후보 선택과 직접 의존하는 의미론만 판단한다. 아래 분류가 과거 packet의 exhaustive D01~D12/G01~G12 요구보다 우선한다. 기존 시험은 보존하지만 전부 통과해야 00A가 완료되는 것은 아니다.

## 1. 후보 선택을 바꿀 수 있는 검증

| 질문 | 확보한 증거 | 선택에 미친 영향 |
|---|---|---|
| 예정 스택이 자연스럽게 연결되는가 | 양쪽 공통 typed read/agent/mutation/wait 흐름; RestateAgent 개별 연결; 실제 PydanticAI + LiteLLM model/MCP 결합 | 두 후보 모두 가능. 구조적 불가능으로 탈락시키지 않음 |
| 상시 구성과 운영 복잡도 | DBOS worker + PostgreSQL; Restate handler + server + 기존 application PostgreSQL | DBOS는 이미 필요한 PostgreSQL을 활용하고 별도 durable 서버/저장소를 추가하지 않음 |
| 구현·유지보수 비용 | 공통 worker와 후보별 process adapter 코드 직접 비교 | 양쪽 모두 얇은 연결 가능. 시험용 제어 코드 LOC를 제품 어댑터 비용으로 오인하지 않음 |
| gateway를 따로 만들 필요가 있는가 | 고정 endpoint, 충돌 없는 두 upstream, 신규 discovery, 실제 MCPToolset 호출, model/MCP 동시 사용 | LiteLLM 선택. FastMCP는 upstream fixture이며 별도 gateway fallback이 아님 |
| 업그레이드가 실행을 버리게 하는가 | 양쪽 V1/V2 복구; 공통 흐름에서 PydanticAI 2.45.0→2.46.0 + 추가 finalization 통과 | DBOS의 명시적 compatibility version 관리 필요. 자동 source hash 변경을 무시하면 안 됨 |

## 2. 우리 아키텍처가 직접 의존하는 의미론

| 의존 | 확보한 증거 / 적용 계약 |
|---|---|
| durable 재실행이 외부 효과를 exactly-once로 만들지는 않음 | 양쪽 실제 commit 직후 kill에서 fixture 호출 2회·적용 1회. 외부 idempotency key와 결과 조회는 애플리케이션 책임 |
| 저장된 모델 결과의 replay | 양쪽 저장 전 종료 시 호출 2회, 저장 후 종료 시 1회. 단계 밖 효과를 숨기지 않음 |
| 사용자 승인 이후 같은 실행 재개 | 양쪽 실제 wait, worker 교체, signal, 완료. Work와 Run의 의미는 자체 소유 |
| 실행 ID와 중복 요청 | 동일 ID 한 논리 실행, 한 Work의 다른 Run은 별도 실행. Restate 중복 main의 409는 output/attach로 처리 |
| timer와 cancel 매핑 | 기존 기본 timer·cancel probe에서 필요한 API 의미론 확인. 추가 장애 조합은 불필요 |
| 추적과 데이터 경계 | 실제 W3C 원래 부모 복원, gateway/agent 단일 trace tree, include_content=False, 로그 카나리 검사. journal은 sensitive store이며 암호화된 텍스트로 간주하지 않음 |
| 실제 선택 조합의 전체 흐름 | `test_combined_gateway_agent.py::test_agent_through_model_and_tool_gateway[durable_crash]`: 실제 model/MCP, 외부 효과, 종료 후 복구, wait/signal, 결과/trace/로그 확인 |

## 3. upstream 재인증에 해당하므로 완료조건에서 제외

- 모든 crash point를 모든 후보·공통 adapter·gateway 조합에 반복 이식하는 작업.
- backend stop/reconnect, 긴 timer, 취소와 worker 부재 등 복합 장애의 조합 확대.
- 모든 D 시나리오별 전후 journal·PID·trace 산출물 완비 및 exhaustive recovery matrix.
- production-grade 장시간 안정성, HA, 장애 복구 속도, 다중 호스트·스토리지 재해 복구 보증.
- 전체 gateway persistence sink나 모든 credential/권한 구성의 인증.

이미 만든 `test_*backend_outage.py`, timer/cancel 복합 시험은 보존한다. 최근 추가 Restate 복합 취소 시험은 worker 부재 상태에서 10초 안에 완료 취소를 관측하지 못했다. 이는 비동기 취소의 요청/완료 구분이 필요한 관측이며 제품 결함·후보 탈락으로 판정하지 않는다. 기존 기본 취소 의미론 증거는 유효하다. 이 실패를 없애려고 추가 장애 실험을 만들지 않는다.

## 4. 선택에 영향이 없어 완료조건에서 제외

- 모든 결과를 동일 JSON으로 다시 포장하고 수동 LOC 수치를 계속 갱신하는 작업.
- 임시 harness를 production SDK 수준의 범용 runner로 추상화하는 작업.
- 사용하지 않는 virtual-key DB·관리형 secret store·세밀한 인자 변환 도입.
- 모든 SDK 부버전 조합, in-flight MCP 세션 투명 복구, 정의 변경 permutation.
- 이미 성공한 시험의 반복과 테스트 개수 증가.

## 증거 해석

- `.artifacts/00a/run.EzB6DW/results.xml`: 공통 crash/wait 및 gateway 시험 성공. 추가 timer 한 건은 결과 뒤 종료 로그를 JSON으로 읽은 test adapter 오류였다.
- `.artifacts/00a/run.bap0Ta/results.xml`: timer 양쪽, DBOS cancel, 양쪽 app/dependency upgrade, gateway privacy/allowlist, model+tool gateway 및 durable crash 결합 성공. Restate 복합 cancel 관측만 실패(위 3번).
- `.artifacts/00a/selection-flow.xml`: 최종 실제 사용 흐름의 선택 확인. 최종 상태는 00A-5를 기준으로 한다.
- 과거 `00a-d*-results.json`과 감사 기록은 당시 범위의 역사적 증거다. 오래된 LOC나 partial 플래그를 현재 선택 gate로 재해석하지 않는다.
- WSL 중단 실행은 사용자 실수로 종료되었다. 결과로 집계하거나 후보 결함으로 취급하지 않는다.

## 과검증 회고

근본 오판은 부족했던 최초 증거를 보완하는 과정에서 ‘선택에 충분한가’를 ‘모든 표의 칸을 같은 형식으로 채웠는가’로 대체한 것이다. 각 부분 성공이 선택 불확실성을 얼마나 줄였는지 확인하지 않아, 이미 확인한 의미론을 공통 runner로 다시 옮기는 활동 자체가 목표가 됐다. 선택 시험, 제품 검증, 결과 포장 작업을 모두 필수 gate로 합친 것이 병목이었다.

AGENTS.md의 기존 원칙 2(목표까지 남은 거리), 4(주장과 직접 증거), 5(위험에 비례한 검증), 6(기준의 무단 확대 방지), 7(규칙 누적 방지)이 이 오류를 충분히 다룬다. 규칙 부족이 아니라 적용 실패였다. 이번에는 각 남은 항목이 선택/아키텍처를 바꾸는지에 따라 위와 같이 분류하고 제거했다. **AGENTS.md에 새 규칙을 추가하지 않는다.**
