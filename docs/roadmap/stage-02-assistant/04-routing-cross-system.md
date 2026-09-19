# Stage 2.4 — Routing and Cross-System Action

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 2.3 완료
- 지금 시작 가능: **아니오**

## Goal

사용자 요청을 적절한 worker/model/resource/project로 보내고, 한 interface의 요청이 다른 project의 실제 mutation으로 이어지게 한다.

## Scope

- worker capability/health
- permission/risk metadata
- provider/model metadata
- budget/cost telemetry
- selection provenance
- fallback/replan
- LiteLLM + Antigravity/OpenCode/Codex 실제 요청 경로
- cross-project resolution
- source-owner-aware mutation

Registry 내부의 고정 sort를 최종 selection policy로 취급하지 않는다.

## Example

Web/Manager에서 Eve project 문제 제기
→ project:eve resolve
→ repository/runtime Work
→ 적절한 worker 실행
→ 수정/검증
→ 같은 중앙 trace로 결과 반환

## Done When

provider/worker failure에도 Goal/provenance를 유지해 fallback 또는 replan하고, 다른 project의 실제 Work까지 이어진다.
