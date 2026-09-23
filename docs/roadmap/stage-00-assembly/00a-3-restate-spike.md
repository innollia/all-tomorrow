# 00A-3 — Restate Spike

## Status

- 상태: **개발완료**
- 선행조건: 00A-1
- 판단 기준: [검증 분류](00a-live-gate-matrix.md)

## 선택에 필요한 결과

Restate Server 1.7.10 / Python SDK 1.0.5 / Python 3.13에서 공통 typed agent, 외부 효과, durable promise 승인·복구를 확인했다. RestateAgent 개별 연결도 가능했다. 저장 전/후 모델 replay, 외부 효과 호출 2회·적용 1회, 다른 Run 분리와 app/dependency upgrade를 확인했다.

중복 main 요청은 409와 동일 invocation ID를 반환한다. 이미 시작된 실행은 output/attach로 조회해야 한다. context와 promise는 후보 adapter에 한정하고 Goal/Work의 canonical state로 쓰지 않는다.

## 비용과 결론

현재 구조에서는 handler 외에 Restate 서버와 별도 journal 저장소를 운영하며 application PostgreSQL도 유지한다. 기능 부적합이나 upstream 신뢰성 부족으로 기각하지 않는다. 두 후보가 필요한 흐름을 지원하므로 현재 단일 노드·PostgreSQL 중심 운영 비용에서 DBOS를 우선한다.

추가 복합 취소 시험의 미완료 관측은 [분류 3](00a-live-gate-matrix.md)에 남겼다. 이를 없애기 위한 제품 재인증은 하지 않는다. Restate 고유 기능/운영 모델이 필요한 상황에서 선택을 재검토한다.
