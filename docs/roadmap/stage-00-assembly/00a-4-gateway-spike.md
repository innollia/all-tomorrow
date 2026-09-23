# 00A-4 — Tool Gateway Spike

## Status

- 상태: **개발완료**
- 선행조건: 00A-1
- 판단 기준: [검증 분류](00a-live-gate-matrix.md)

## 결정: LiteLLM Proxy 1.101.0

PydanticAI MCPToolset의 `all-tomorrow-tools` ID와 고정 `/mcp` endpoint로 두 upstream의 동명 도구를 충돌 없이 조회·호출했다. 설정에 세 번째 upstream을 추가하고 재시작한 뒤 신규 client가 발견했다. 정의 JSON과 SHA-256을 저장·비교할 수 있다.

실제 PydanticAI 실행에서 LiteLLM model route와 MCP route가 함께 동작했다. OTel content 수집을 끄고 단일 trace tree, prompt/key 로그 카나리 부재를 확인했다. 서버 allowlist는 목록과 직접 호출을 제한했다. 환경 참조로 master key를 주입했다. DB 없는 잘못된 키 요청은 400으로 fail-closed되며, 가상 키별 권한을 제공한다고 주장하지 않는다.

## 채택 계약

- gateway는 별도 Python 환경에서 `deploy/gateway/requirements.txt`의 exact version을 사용한다.
- 초기 단일 신뢰 호출자, 정적 registry, 서버 allowlist로 시작한다. DB/virtual keys는 실제 필요할 때 추가한다.
- config 변경은 gateway restart로 반영하고 새 Run마다 discovery한다. 시작 시 정의와 fingerprint를 기록한다.
- 진행 중 도구 계약을 조용히 교체하지 않는다. 기존 Run에는 호환 upstream을 유지하거나 명시적 migration을 한다.
- provider credential은 gateway runtime env 소유, 외부 logging callbacks와 원문 수집은 비활성화한다.
- model/MCP를 한 프로세스에 두므로 프로세스 장애 영역은 공유한다. 이 비용을 현재 규모에서 수용한다. 분리가 필요해질 때 FastMCP fallback을 검토한다.
- 새 버전 PR에서 실제 agent discovery/call·structured output·privacy 계약을 재확인한다. 모든 장애 조합은 요구하지 않는다.

FastMCP 4.0.5는 시험 upstream/client였다. 별도의 FastMCP gateway 또는 background durability를 채택하지 않았다.
