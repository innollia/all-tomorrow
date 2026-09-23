# 00A-2 — DBOS Spike

## Status

- 상태: **개발완료**
- 선행조건: 00A-1
- 판단 기준: [검증 분류](00a-live-gate-matrix.md)

## 선택에 필요한 결과

DBOS 3.0.0 / Python 3.13 / PostgreSQL에서 공통 typed agent와 외부 효과, 승인 대기·복구가 구현됐다. 동일 workflow ID의 중복 시작과 별도 Run 분리, 저장된 모델 결과 재사용을 확인했다. commit 직후 worker 종료에서는 호출 2회·외부 적용 1회로 애플리케이션 idempotency seam을 확인했다.

일반 코드 교체와 PydanticAI 2.45.0→2.46.0 시험에서 기존 모델 결과를 재사용하고 새 finalization을 완료했다. **호환 코드의 application_version을 명시적으로 유지해야 한다.** 비호환 변경은 이전 worker를 유지해 drain하며, compatibility version을 무조건 고정하는 전략은 사용하지 않는다.

시스템 DB는 입력과 단계 결과를 저장한다. 입력 metadata 카나리가 base64 pickle에서 관측됐으며 암호화를 뜻하지 않는다. 최소 입력·artifact 참조, 접근 제한, 저장소 암호화와 백업/보존 책임이 필요하다.

## 비용과 결론

기존 PostgreSQL과 worker로 시작할 수 있고, 별도 durable 서버를 추가하지 않는다. 이 점을 주요 선택 근거로 DBOS를 채택한다. Conductor/HA/다중 호스트 설계와 queue 최적화는 현재 선택 조건이 아니다. [최종 계약과 선택](00a-5-selection.md)을 따른다.
