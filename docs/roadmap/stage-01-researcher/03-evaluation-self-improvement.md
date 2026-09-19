# Stage 1.3 — Evaluation and Self-Improvement

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 02 Researcher Loop 완료

## 기본 조립

- evaluation dataset/runner: Pydantic Evals 우선
- code change rail: Git branch/commit/PR
- regression gate: GitHub Actions
- execution telemetry: OpenTelemetry
- production promotion/rollback: All Tomorrow policy + deployment adapter
- protected approval: laptop Approval Authority

Promptfoo/Langfuse를 초기 필수 dependency로 넣지 않는다.

Promptfoo는 adversarial/red-team 요구가 실제로 생길 때,
Langfuse는 telemetry backend가 필요해질 때 후보로 검토한다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 03A | Evaluation/Proposal Persistence | 선행작업 대기 | 아니오 | 02 |
| 03B | Pydantic Evals + Domain Metrics | 선행작업 대기 | 아니오 | 03A |
| 03C | Git Sandbox Experiment | 선행작업 대기 | 아니오 | 03A + 03B |
| 03D | CI-Gated Ordinary Promotion & Rollback | 선행작업 대기 | 아니오 | 03C |
| 03E | Protected Classification & Laptop Handoff | 선행작업 대기 | 아니오 | 03A + 03C |
| 03F | Acceptance | 선행작업 대기 | 아니오 | 03A~03E |

## Version-safe Self Change

durable workflow가 살아 있는 동안 application code가 바뀔 수 있다.

따라서 ordinary self-promotion도:
- 새 version 배포
- old in-flight execution drain/recovery
- regression/eval 통과
- rollback

을 하나의 acceptance로 본다.

새 코드가 올라갔다는 이유로 old workflow를 버리지 않는다.
