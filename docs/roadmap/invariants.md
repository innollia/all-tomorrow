# Cross-Stage Invariants

이 파일은 아키텍처 경계, permission, self-improvement, ownership, genericity, 외부 substrate 교체를 건드리는 작업에서 읽는다.

## Invariants

1. Original Vision이 파생 설계보다 우선한다.
2. Control Plane은 serial brain이 아니라 shared authority/state다.
3. Work와 metacognition은 병렬로 동작한다.
4. Metacognition은 자기 자신의 기록도 관찰하며 meta-meta 계층을 무한히 쌓지 않는다.
5. Pipeline/workflow engine은 bounded execution mechanism이며 Goal의 의미를 소유하지 않는다.
6. 문제/해결 taxonomy를 닫힌 목록으로 가정하지 않는다.
7. Durable Work의 의미는 특정 durable backend보다 위에 있다.
8. 외부 OSS의 내부 DB/status/id를 All Tomorrow domain 정본으로 승격하지 않는다.
9. commodity mechanism은 직접 재구현하기 전에 기존 OSS로 충족 가능한지 먼저 검증한다.
10. 외부 substrate는 얇은 adapter와 stable semantic contract 뒤에 둔다.
11. source ownership은 중앙집권 뒤에도 유지한다.
12. ordinary self-change도 frozen evaluation, monitoring, rollback을 가진다.
13. protected/unknown authority expansion은 laptop Approval Authority 없이는 production 적용 불가다.
14. inferred preference로 사용자의 명시적 선택을 몰래 바꾸지 않는다.
15. user-owned high-priority commitment가 autonomous background work보다 우선한다.
16. 필수 정보가 없으면 fabrication 대신 NEED_USER/UNKNOWN을 사용한다.
17. provider/project/host 이름별 branch를 generic core에 축적하지 않는다.
18. secret 값은 event/prompt archive/artifact metadata/lesson 같은 장기 기록에 평문 저장하지 않는다.
19. telemetry backend가 바뀌어도 trace/provenance identity가 살아남아야 한다.
20. durable backend 교체가 Goal/Work/Run schema 의미 재정의를 요구하면 경계 설계 실패다.
21. Work는 여러 Run을 가질 수 있고 ExecutionRef는 Run이 소유한다.
22. 같은 logical attempt의 crash/recovery는 새 Run이 아니며 semantic retry/replan은 새 Run이다.
23. external mutation invocation과 committed effect를 구분한다.
24. unknown/missing measurement를 success/0/empty로 위조하지 않는다.
25. 높은 evidence level requirement를 mock/unit 통과로 대체하지 않는다.
26. immutable artifact/hash가 필요한 approval/evaluation에서 mutable path를 identity로 쓰지 않는다.
27. 상위 identity/ownership/retry/security contract 변경은 downstream plan/완료 상태 재검토를 요구한다.

세부 공통 계약:
- plan-verification-contract.md
- domain-contracts.md
- failure-recovery-contract.md
- data-security-artifact-contract.md

세부 self-modification 경계는 ../decisions/0004-self-modification-and-approval-boundary.md를 따른다.
OSS 조립 원칙은 ../decisions/0005-assemble-open-source-substrates.md를 따른다.
