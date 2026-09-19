# All Tomorrow Roadmap

이 파일은 **master status index**다. 세부 구현 계획을 여기에서 읽지 않는다.

## Current Position

| Stage | 상태 | 지금 시작 가능 | 선행조건 | 상세 |
|---|---|---:|---|---|
| 1. Durable Self-Improving Researcher | 개발중 | 예 | 없음 | [status/index](roadmap/stage-01-researcher/index.md) |
| 2. Reliable Assistant & Remote Control | 선행작업 대기 | 아니오 | Stage 1 완료 | [status/index](roadmap/stage-02-assistant/index.md) |
| 3. Personal Manager & Generalized Autonomy | 선행작업 대기 | 아니오 | Stage 2 완료 | [status/index](roadmap/stage-03-manager/index.md) |

## 지금 바로 작업 가능한 것

Stage 1 인덱스를 기준으로 현재 병렬 착수 가능:

- Minimal Durable Kernel — 개발중
- Runtime & Tool Surface — 개발중

Researcher Loop는 Durable Kernel 완료를 기다린다.

## 제품 완성 순서

1. Researcher
2. Reliable assistant
3. Personal manager

구현 의존성 때문에 researcher 전에 최소 durable kernel이 필요하지만, durable core 자체를 첫 제품으로 취급하지 않는다.

## 필요한 문서만 읽기

- 작업 파일 찾기: [roadmap file map](roadmap/README.md)
- 구조/권한 변경 작업만: [cross-stage invariants](roadmap/invariants.md)
- 원문 요구 누락 감사만: [vision coverage](roadmap/vision-coverage.md)
- 전체 기술 구조가 정말 필요할 때만: [architecture](architecture.md)
- 확정된 결정 확인이 필요할 때만: [decisions](decisions/)

## 상태 정의

- **개발중**: 현재 구현/수정 중
- **개발완료**: 해당 파일 Done When 실제 충족
- **시작안했음**: 선행조건은 충족됐지만 미착수
- **선행작업 대기**: 다른 작업 완료 전 착수하지 않음

파일이나 prototype이 존재한다는 이유만으로 개발완료로 표시하지 않는다.
