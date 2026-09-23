# Stage 3.4 — Long-Horizon Autonomous Production

## Status
- 상태: 선행작업 대기
- 선행조건: 3.2 + 3.3
- 지금 시작 가능: 아니오

## Packets
| 순서 | 작업 | 선행조건 |
|---:|---|---|
| 3.4A | Dynamic Work Graph | 3.2 |
| 3.4B | Milestone / Artifact Progress | 3.4A |
| 3.4C | Multi-day Resume & Resource Change | 3.4A+B + 3.3 |
| 3.4D | Artifact-bound Feedback | 3.4B |
| 3.4E | Acceptance | 3.4A~D |

파일: [04-long-horizon/](04-long-horizon/)

## 확정
1차 dependency blocking은 별도 BLOCKED state를 추가하지 않고 Work WAITING + wait_reason=dependency_blocked로 표현한다.

## Exit
activity가 아니라 versioned milestone + Outcome + immutable Artifact evidence로 장기 Goal 진전을 증명해야 한다.
