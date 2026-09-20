# 03E — Protected Change Classification and Handoff

## Status

- 상태: **선행작업 대기**
- 선행조건: 03A + 03C
- 지금 시작 가능: **아니오**
- 실제 승인 적용 선행조건: 04E Laptop Approval Authority
- contracts: ../../data-security-artifact-contract.md

## 목적

mechanical protected surface + semantic authority expansion + unknown-impact fail-closed rule로 protected proposal을 automatic promotion에서 제외한다.

## Mechanical protected surfaces

예:

- approval authority code/config/data
- deployment/signing credential refs
- budget/concurrency/rate ceilings
- secret/permission policy
- production write role/policy
- kill switch
- rollback enforcement
- audit/provenance enforcement
- classifier/protection policy 자체
- retention/security policy

실제 목록은 versioned config/hash로 관리한다.

## Semantic signals

- 비용/자원 ceiling 확대
- permission/secret scope 확대
- production write 확대
- approval 약화
- rollback/audit/kill-switch 약화
- protected surface 축소
- 우회 경로 생성
- 새로운 credential/deployment surface 생성

## Fail-closed

다음이면 APPROVAL_REQUIRED:

- mechanical touch
- semantic detector protected
- detector 결과 unknown/insufficient
- 새 미분류 authority surface 영향
- classifier/policy 자체 변경

ordinary임을 증명하지 못한 변경을 ordinary로 간주하지 않는다.

## Handoff package

immutable:

- proposal_id/revision
- candidate artifact hash/version
- baseline hash/version
- frozen evaluation refs
- protected reason list
- requested boundary change
- protection policy version
- nonce
- expiry

candidate/proposal/protection policy가 바뀌면 prior handoff invalid.

## Requirements

| ID | 요구 | 검증 |
|---|---|---|
| 03E-01 | known authority expansion protected | fixtures |
| 03E-02 | unknown classifier result protected | negative |
| 03E-03 | mechanical touch가 semantic ordinary를 override | negative |
| 03E-04 | classifier 자체 변경 protected | fixture |
| 03E-05 | artifact/proposal hash 변경 시 handoff invalid | integrity |
| 03E-06 | AWS ordinary path가 APPROVAL_REQUIRED apply 못함 | integration |

## 완료조건

분류 누락이 권한 확대로 이어질 수 없고 exact immutable approval package만 04E로 전달되어야 한다.
