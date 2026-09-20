# Stage 1.3 — Evaluation and Self-Improvement

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 02 Researcher Loop 완료

## 기본 조립

- evaluation runner: Pydantic Evals 우선
- candidate rail: immutable Git/artifact refs
- sandbox: target adapter + bounded permissions
- regression gate: GitHub Actions
- telemetry: OpenTelemetry
- promotion/rollback: target-specific deployment adapter
- protected apply: laptop Approval Authority

Promptfoo/Langfuse는 실제 requirement가 생길 때만 후보로 추가한다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 03A | Evaluation/Proposal Persistence | 선행작업 대기 | 아니오 | 02 |
| 03B | Frozen Mixed Evaluation | 선행작업 대기 | 아니오 | 03A |
| 03C | Sandbox Experiment | 선행작업 대기 | 아니오 | 03A + 03B |
| 03D | Ordinary Promotion & Rollback | 선행작업 대기 | 아니오 | 03C |
| 03E | Protected Classification & Handoff | 선행작업 대기 | 아니오 | 03A + 03C |
| 03F | Acceptance | 선행작업 대기 | 아니오 | 03A~03E |

## Version-safe self-change

ordinary self-change도 다음을 한 acceptance로 본다.

- criteria/cases candidate 실행 전 freeze
- sandbox evidence
- immutable candidate identity
- target-specific deployment
- old in-flight execution replay/drain
- monitoring policy
- exact rollback

new code가 배포됐다는 사실만으로 old workflow를 버리지 않는다.
