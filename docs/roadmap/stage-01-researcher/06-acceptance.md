# Stage 1.6 — Acceptance

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01~05 완료

## Acceptance 축

Stage 1 완료는 기능 데모만으로 판정하지 않는다.

필수:
- real PostgreSQL
- process kill/restart
- duplicate start/idempotency
- NEED_USER 중단·재개
- model gateway 장애
- worker timeout
- application version upgrade 중 in-flight work
- OTel trace/provenance linkage
- eval regression
- ordinary self-change rollback
- protected change laptop boundary
- backend 내부 상태를 지워 읽지 않고도 All Tomorrow domain 의미 설명 가능

## Backend Escape

DBOS는 초기 implementation이지 제품 정의가 아니다.

DurableExecutionPort의 fake/alternate adapter contract test를 통과해야 한다.

Stage 1을 개발완료 처리하기 위해 Hatchet/Temporal을 실제 production 배포할 필요는 없다.

mock/unit test만으로 Stage 1을 개발완료 처리하지 않는다.
