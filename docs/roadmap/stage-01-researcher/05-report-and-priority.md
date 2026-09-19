# Stage 1.5 — Daily Report and User Priority

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 02-researcher-loop 완료
- 추가 의존성: 실제 비용/host 정보는 04-runtime-and-tools 필요

## Goal

Researcher가 혼자 움직인 결과를 사용자가 복원할 수 있게 하고, user-owned priority가 autonomous work를 이기도록 한다.

## Daily Report

최소 항목:

- 새로 자율 생성한 Goal
- 진행/완료/중단한 autonomous Work
- 조사 내용과 핵심 결과
- 자동 적용한 self-improvement
- rollback/rejection
- 사용한 자원/비용 요약
- 보호 변경 승인 대기 proposal
- 사용자 판단이 필요한 질문

사용자 생성 Goal과 autonomous Goal을 provenance에서 구분한다.

보고서는 Event dump가 아니라 오늘 시스템이 무엇을 원해서 무엇을 했고 무엇이 달라졌는지 복원하는 요약이다.

## User Priority

priority는 user-owned policy로 결정한다.

현재 중요한 예:

- 학교 수행평가 또는 AI 활용 대회 참여처럼 실제 commitment가 높은 요청은 잘못 돌고 있던 background work를 yield/cancel하고 가용 자원을 우선 사용
- "이거 재밌겠다. 한번 만들어봐." 같은 낮은 commitment 발화는 즉시 전체 자원을 점유하지 않고 TODO/Goal 후보로 남길 수 있음

학교/대회 이름을 generic core switch문으로 만들지 않는다. 이는 현재 사용자 정책의 예다.

## Done When

1. autonomous Goal/Work 변화가 일일보고서에서 복원 가능
2. ordinary self-change와 protected pending proposal이 구분되어 보임
3. high-priority user request가 background work를 yield시킴
4. low-commitment idea가 즉시 강제 실행되지 않을 수 있음
