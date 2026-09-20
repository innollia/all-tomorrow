# Roadmap File Map

이 디렉터리는 작업자가 필요한 계획 파일만 읽도록 stage 계획을 책임 단위로 분리한다.

## 전체 상태

| Stage | 상태 | 지금 시작 가능 | 선행조건 | 인덱스 |
|---|---|---:|---|---|
| 0. OSS Assembly & Architecture Proof | 개발중 | 예 | 없음 | [stage-00-assembly](stage-00-assembly/index.md) |
| 1. Durable Self-Improving Researcher | 선행작업 대기 | 아니오 | Stage 0 | [stage-01-researcher](stage-01-researcher/index.md) |
| 2. Reliable Assistant & Remote Control | 선행작업 대기 | 아니오 | Stage 1 | [stage-02-assistant](stage-02-assistant/index.md) |
| 3. Personal Manager & Generalized Autonomy | 선행작업 대기 | 아니오 | Stage 2 | [stage-03-manager](stage-03-manager/index.md) |

## 공통 계약

00B 이후의 계획은 다음 네 문서를 공통 기반으로 사용한다.

- [Plan & Verification Contract](plan-verification-contract.md)
- [Canonical Domain Contracts](domain-contracts.md)
- [Failure, Retry & Recovery Contract](failure-recovery-contract.md)
- [Data, Security & Artifact Contract](data-security-artifact-contract.md)

packet이 공통 계약과 충돌하면 packet을 구현하기 전에 먼저 계획을 수정한다.

## 읽기 규칙

작업 시작 시 기본적으로 다음만 읽는다.

1. docs/roadmap.md에서 현재 stage 확인
2. 해당 stage의 index.md
3. 실제 작업과 직접 관련된 packet 하나
4. packet이 참조하는 공통 contract/ADR만 추가 확인
5. packet이 직접 요구하는 코드만 추가 확인

Stage 0 작업자는 기존 Stage 1 세부 packet을 구현 지시로 사용하지 않는다. Stage 0의 목적 중 하나가 그 packet에서 외부 OSS와 겹치는 부분을 제거하는 것이다.

## 상태 표기

- 개발중
- 개발완료
- 시작안했음
- 선행작업 대기

파일이 존재하거나 prototype 코드가 있다는 이유만으로 개발완료로 올리지 않는다.

## 문서 역할

- docs/roadmap.md: 제품 순서와 stage 경계
- 공통 contract: identity, 실패/복구, 데이터/보안, 검증 수준
- stage-00-assembly: 외부 OSS를 실제로 연결해 foundation을 검증
- stage-*/index.md: 상태판 + 파일 라우터
- stage 세부 파일: 구현 범위, 선행조건, packet 고유 acceptance
- docs/architecture.md: 검증 뒤 확정되는 공통 architecture reference
- docs/decisions/*.md: 확정된 구조 결정
