# 03E — Protected Change Classification and Handoff

## Status

- 상태: **선행작업 대기**
- 선행조건: 03A + 03C
- 지금 시작 가능: **아니오**
- 실제 승인 적용 선행조건: 04E Laptop Approval Authority

## 목적

"semantic 판단 하나"만 믿지 않고 mechanical protected surface + semantic expansion detection을 결합해 protected proposal을 자동 promotion path에서 제외한다.

## 수정 파일

- 새 파일: `src/all_tomorrow/protection.py`
- 수정: `src/all_tomorrow/promotion.py`
- 새 config: `config/protected-surfaces.example.yaml`
- 새 테스트: `tests/test_protection.py`

## Mechanical protected surface

초기 protected resource 예:

- approval authority code/config
- production deployment credential refs
- budget ceiling config
- concurrency/rate ceiling config
- secret permission policy
- production write role/policy
- kill switch
- rollback enforcement
- audit/provenance enforcement

실제 writable credential boundary는 04E/deployment가 강제.

이 목록은 problem taxonomy가 아니라 security authority surface다.

## Semantic expansion detection

proposal diff/effect summary에서 다음을 별도 signal로 판단:

- 비용 상한 증가
- concurrency/rate 확대
- permission scope 확대
- secret scope 확대
- production write 확대
- approval requirement 약화
- rollback/audit/kill-switch 약화
- protected surface 축소/우회 경로 생성

semantic detector가 ordinary라고 말해도 mechanical protected resource touch면 protected.

둘 중 하나라도 protected면 APPROVAL_REQUIRED.

## Handoff record

04E로 넘길 exact package:

- proposal_id
- candidate artifact/hash/version
- baseline ref/hash
- protected reason list
- evaluation refs
- requested boundary change
- nonce/expiry

approval은 이 exact candidate에만 유효.

## 테스트

- budget 10→20 protected
- concurrency 4→8 protected
- production write permission 추가 protected
- approval bypass code path protected
- prompt wording change ordinary
- internal refactor ordinary
- mechanical touch + semantic ordinary → protected
- candidate hash 변경 → prior handoff invalid

## 완료조건

AWS ordinary promotion path가 protected proposal을 fail closed하고 exact approval package만 생성.

실제 승인/적용 보안은 04E 완료조건에서 검증.
