# Roadmap File Map

이 디렉터리는 작업자가 필요한 계획 파일만 읽도록 stage 계획을 책임 단위로 분리한다.

## 상태 표기

| 상태 | 의미 |
|---|---|
| 개발중 | 현재 구현 또는 수정 중 |
| 개발완료 | 해당 파일의 완료조건을 실제로 충족 |
| 시작안했음 | 선행조건은 충족됐지만 아직 착수하지 않음 |
| 선행작업 대기 | 다른 작업이 끝나야 시작 가능 |

"파일이 존재함"이나 "골격 코드가 있음"만으로 개발완료로 올리지 않는다.

## 전체 상태

| Stage | 상태 | 지금 시작 가능 | 선행조건 | 인덱스 |
|---|---|---:|---|---|
| 1. Durable Self-Improving Researcher | 개발중 | 예 | 없음 | [stage-01-researcher](stage-01-researcher/index.md) |
| 2. Reliable Assistant & Remote Control | 선행작업 대기 | 아니오 | Stage 1 완료 | [stage-02-assistant](stage-02-assistant/index.md) |
| 3. Personal Manager & Generalized Autonomy | 선행작업 대기 | 아니오 | Stage 2 완료 | [stage-03-manager](stage-03-manager/index.md) |

## 읽기 규칙

작업 시작 시 기본적으로 다음만 읽는다.

1. 이 파일에서 현재 stage 확인
2. 해당 stage의 index.md
3. 실제 작업과 직접 관련된 세부 계획 파일 하나
4. 세부 파일의 Read with가 가리키는 ADR/architecture만 추가로 읽기

stage 전체 문서를 매번 전부 읽지 않는다.

## 문서 역할

- docs/roadmap.md: 제품 순서와 stage 경계
- docs/roadmap/stage-*/index.md: 상태판 + 파일 라우터
- stage 세부 파일: 실제 구현 범위, 선행조건, 완료조건, 비범위
- docs/architecture.md: 공통 architecture reference
- docs/decisions/*.md: 이미 확정된 구조 결정
