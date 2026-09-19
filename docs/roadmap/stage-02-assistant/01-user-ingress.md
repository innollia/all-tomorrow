# Stage 2.1 — User Ingress

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 1 완료
- 지금 시작 가능: **아니오**

## Goal

Web, Discord, CLI/API가 같은 중앙 Goal/Work authority로 들어오게 한다.

## Scope

- authenticated Web request ingress
- Discord local-vs-central escalation
- CLI/API ingress
- duplicate delivery deduplication
- original user message/provenance 보존
- client마다 별도 task/history 섬을 만들지 않음

Discord는 모든 대화를 중앙에 보내지 않는다.

## Done When

1. 서로 다른 ingress가 같은 Request/Goal/Work contract 사용
2. duplicate request가 duplicate mutation을 만들지 않음
3. local conversation은 필요 없이 중앙 Work를 만들지 않음
