# Stage 2.2 — Remote Control Surface

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 2.1 + Stage 1 runtime
- 지금 시작 가능: **아니오**

## Goal

AWS의 중앙 runtime을 실제 어느 기기에서나 접근 가능한 control surface로 만든다.

## Scope

- HTTPS
- authenticated Web access
- secure session
- store-backed Goal/Work/Run view
- pending question/answer
- artifact/result link
- health/readiness
- persistent PostgreSQL
- restart recovery
- backup/restore 최소 검증
- secret separation

현재 표시용 prototype WebState를 production authority로 사용하지 않는다.

## Done When

노트북 밖 기기에서 로그인 → Work 제출 → 상태 추적 → 질문 응답 → 결과 확인이 restart를 견딘다.
