# 03D — Ordinary Promotion and Rollback

## Status

- 상태: **선행작업 대기**
- 선행조건: 03C 완료
- 지금 시작 가능: **아니오**

## 목적

protected boundary를 넓히지 않는 평가 통과 변경을 자동 production promotion하고, 회귀 시 이전 version으로 되돌린다.

## 수정 파일

- 새 파일: `src/all_tomorrow/promotion.py`
- 수정: `src/all_tomorrow/evaluation.py`
- 수정: `src/all_tomorrow/storage/postgres.py`
- 새 테스트: `tests/test_promotion.py`

## PromotionTarget adapter

interface:

- inspect_current()
- validate_candidate()
- apply(candidate_ref)
- verify()
- rollback(previous_ref)

구현 후보:

- versioned prompt/config
- pipeline version
- code/repository deploy adapter

core promotion service는 target별 filesystem detail을 모름.

## Promotion flow

1. proposal ACCEPT
2. protection classification 확인
3. ordinary만 proceed
4. current target ref/hash 재확인
5. candidate apply
6. smoke verify
7. proposal PROMOTED + Event
8. monitoring window 등록

apply 중 baseline이 proposal 생성 시점과 달라졌으면 stale proposal로 중단하고 재평가.

## Rollback trigger

초기 자동 rollback 신호:

- explicit deploy/smoke failure
- clear monitored regression
- repeated critical failure threshold

ambiguous quality decline는 곧바로 rollback하지 않고 evaluation Work 생성 가능.

rollback:

- exact previous_ref로 복귀
- proposal ROLLED_BACK
- rollback Event
- 원인 investigation Work 후보

## 보고

ordinary promotion/rollback은 05 report 입력으로 Event 남김.

## 테스트

- accepted ordinary change promotion
- stale baseline blocks
- apply failure rollback
- verify failure rollback
- repeated rollback idempotency
- protected proposal promotion reject

## 완료조건

평가 통과 ordinary change가 사람 승인 없이 적용 가능하고 exact previous version으로 rollback 가능.
