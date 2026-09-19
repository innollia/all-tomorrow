# Cross-Stage Invariants

이 파일은 일반 작업마다 읽지 않는다.

아키텍처 경계, permission, self-improvement, ownership, genericity를 건드리는 작업에서만 읽는다.

## Invariants

1. Original Vision이 파생 설계보다 우선한다.
2. Control Plane은 serial brain이 아니라 shared authority/state다.
3. Work와 metacognition은 병렬로 동작한다.
4. Metacognition은 자기 자신의 기록도 관찰하며 meta-meta 계층을 무한히 쌓지 않는다.
5. Pipeline은 bounded execution recipe다.
6. 문제/해결 taxonomy를 닫힌 목록으로 가정하지 않는다.
7. Durable Work는 Run보다 위에 있다.
8. source ownership은 중앙집권 뒤에도 유지한다.
9. ordinary self-change도 evaluation과 rollback을 가진다.
10. protected authority expansion은 laptop Approval Authority 없이는 production 적용 불가다.
11. inferred preference로 사용자의 명시적 선택을 몰래 바꾸지 않는다.
12. user-owned high-priority commitment가 autonomous background work보다 우선한다.
13. 필수 정보가 없으면 fabrication 대신 NEED_USER를 사용한다.
14. provider/project 이름별 branch를 generic core에 축적하지 않는다.
15. secret 값은 event/prompt archive/artifact metadata/lesson 같은 장기 기록에 평문 저장하지 않는다.

세부 self-modification 경계는 ../decisions/0004-self-modification-and-approval-boundary.md를 따른다.
