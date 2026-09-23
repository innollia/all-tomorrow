# Roadmap Plan & Verification Contract

이 문서는 00B 이후 모든 roadmap packet의 공통 작성·완료 계약이다. 각 packet은 이 문서를 반복하지 않고 packet 고유 요구와 증거만 추가한다.

## 1. Requirement traceability

모든 구현 요구에는 안정적인 requirement id를 붙인다.

각 packet은 최소한 다음 표를 가진다.

| Requirement | 구현 위치 | 검증 | 필수 증거 | 실패 시 완료 가능 |
|---|---|---|---|---|
| packet-specific id | file/module/schema | test/scenario | observable artifact/log/state | 아니오 |

테스트 개수는 완료 증거가 아니다. 각 requirement가 실제로 어떤 관측값으로 닫혔는지가 완료 기준이다.

## 2. Observable acceptance contract

"복구된다", "유지된다", "안전하다" 같은 문장은 단독 완료조건으로 쓰지 않는다. 검증 가능한 요구는 다음을 명시한다.

- setup/input
- 실행 경계와 사용한 실제 component
- failure injection 또는 competing condition
- 관측할 application state
- 관측할 external state/effect
- 기대 결과
- 명시적 불합격 조건
- 재현 명령 또는 test entrypoint

실제 process crash를 요구하는 scenario는 예외 주입이나 함수 return으로 대체하지 않는다. 별도 OS process를 synchronization barrier에서 종료하고 새 process에서 복구한다.

## 3. Evidence levels

- L0: pure unit/contract test. 외부 substrate 없음.
- L1: 실제 PostgreSQL/실제 선택 substrate를 사용한 local integration.
- L2: 별도 process 또는 host boundary를 가진 crash/restart/upgrade integration.
- L3: 실제 배치 topology에서의 operational/security boundary 검증.

각 requirement는 필요한 최소 level을 packet에서 명시한다. 높은 level 요구를 낮은 level mock으로 대체해 완료 처리하지 않는다.

## 4. Wrong-implementation test

장애·중복·권한·보안·reconciliation requirement는 정상 구현이 통과하는 것뿐 아니라 대표적인 잘못된 구현이 실패하도록 fixture 또는 negative assertion을 둔다.

예:
- duplicate side effect를 허용하면 실패
- caller가 원래 correlation 값을 다시 주입하면 실패
- mock-only crash가 process-kill requirement를 만족하지 못함
- protected credential을 AWS가 가지면 실패

## 5. Completion gate

packet은 다음을 모두 만족할 때만 개발완료다.

1. requirement table의 필수 항목 모두 구현됨
2. 각 requirement의 요구 evidence level 충족
3. negative/failure path 검증
4. 새 unresolved design choice가 downstream input으로 남지 않음
5. 관련 parent/index 상태와 실제 상태 일치
6. 미측정 값은 성공/0으로 추정하지 않고 unknown으로 남김

부분 구현은 개발중으로 유지한다.

implementation-ready packet은 구현 경로와 테스트 경로가 비어 있으면 시작안했음/개발중으로 올리지 않는다. 선행 evidence 때문에 아직 경로를 확정할 수 없으면 evidence blocker와 확정 시점을 명시한다.

## 6. Upstream invalidation

상위 contract가 변경되면 영향을 받는 downstream packet을 즉시 재검토 대상으로 표시한다.

특히 다음 변경은 downstream 재검토를 강제한다.

- identity/state semantics
- ownership boundary
- durable substrate/version
- retry/reconciliation policy
- authority/security boundary
- artifact/data retention contract
- model/tool gateway contract

이미 개발완료인 downstream도 새로운 contract와 충돌하면 완료 상태를 유지하지 않는다.

## 7. Packet 최소 형식

새 packet 또는 대규모 rewrite는 최소한 다음을 포함한다.

1. 목적
2. 선행조건과 소비하는 상위 contract
3. 입력/출력
4. owned state와 non-owned state
5. interface/state transition
6. invariants
7. 구현 단위
8. failure/concurrency/upgrade scenario
9. requirement traceability
10. 검증 환경과 evidence level
11. 완료조건
12. 비범위
13. downstream에 넘기는 확정 산출물
14. 구현 예정 위치: code/module/migration/config/test 경로 또는 stage implementation-map entry

## 8. 상태표 일관성

local packet이 "지금 시작 가능=예"이면 parent index도 그 사실을 반영해야 한다. parent의 선행작업 대기와 child의 시작 가능이 충돌하면 parent index를 authoritative하게 고치기 전에는 작업을 시작하지 않는다.
