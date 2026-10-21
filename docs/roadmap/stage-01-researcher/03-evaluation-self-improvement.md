# Stage 1.3 — Evaluation and Self-Improvement

## Status

- 상태: **개발중**
- 지금 시작 가능: **예**
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
| 03A | Evaluation/Proposal Persistence | 개발중 | 아니오 | 02 |
| 03B | Frozen Mixed Evaluation | 개발중 | 아니오 | 03A |
| 03C | Sandbox Experiment | 개발중 | 아니오 | 03A + 03B |
| 03D | Ordinary Promotion & Rollback | 개발중 | 아니오 | 03C |
| 03E | Protected Classification & Handoff | 개발중 | 아니오 | 03A + 03C |
| 03F | Acceptance | 개발중 | 아니오 | 03A~03E |

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

## 2026-10-21 상태 정정

기존 부품의 존재와 단위시험을 Stage 전체 운영 완료로 표시하지 않는다. [DP7 자기개선 고리](../../dp7-loop.md)에 연결 경로와 남은 검증을 기록했다. 메타인지→영속 Work→사본 실행→시험→반영/되돌림→Event→다음 관측→보고 적재를 연결했다. 실제 DB·Discord·재부팅 검증은 확인 전이다. 서버와 실행기는 DP7, 노트북은 기록 전용이다. 기존 일일 보고 composer나 보호 변경 승인 경계 전체를 완료한 것은 아니다.
