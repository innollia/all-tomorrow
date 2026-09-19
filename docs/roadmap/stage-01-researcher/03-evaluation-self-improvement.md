# Stage 1.3 — Evaluation and Self-Improvement

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 02 Researcher Loop 완료

이 파일은 03 작업의 local index다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 03A | Improvement/Evaluation Persistence | 선행작업 대기 | 아니오 | 02 완료 | [03a](03-evaluation-self-improvement/03a-persistence.md) |
| 03B | Mixed Evaluator | 선행작업 대기 | 아니오 | 03A | [03b](03-evaluation-self-improvement/03b-mixed-evaluator.md) |
| 03C | Generic Sandbox Experiment | 선행작업 대기 | 아니오 | 03A + 03B | [03c](03-evaluation-self-improvement/03c-sandbox-experiment.md) |
| 03D | Ordinary Promotion & Rollback | 선행작업 대기 | 아니오 | 03C | [03d](03-evaluation-self-improvement/03d-promotion-rollback.md) |
| 03E | Protected Classification & Handoff | 선행작업 대기 | 아니오 | 03A + 03C | [03e](03-evaluation-self-improvement/03e-protection-classification.md) |
| 03F | Acceptance | 선행작업 대기 | 아니오 | 03A~03E | [03f](03-evaluation-self-improvement/03f-acceptance.md) |

## 중요 의존성

03은 protected 변경을 **분류하고 approval package를 만드는 데까지** 닫는다.

실제 protected apply 권한과 재인증 UI는 04E Laptop Approval Authority가 담당한다. 이 분리로 03↔04E 순환 의존성을 피한다.
