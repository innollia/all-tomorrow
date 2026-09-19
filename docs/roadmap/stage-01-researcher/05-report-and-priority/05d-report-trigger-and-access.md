# 05D — Report Trigger and Minimal Access

## Status

- 상태: **선행작업 대기**
- 선행조건: 05A + 05B + 04D AWS Runtime
- 지금 시작 가능: **아니오**

## 목적

Stage 2 full assistant UI 전에도 일일보고서가 실제로 생성되고 사용자가 볼 수 있게 한다.

## 수정 파일

- 수정: AWS service/runtime loop
- 수정: `src/all_tomorrow/web.py`
- 수정: `tests/test_web.py`
- 보강: `tests/test_reports.py`

## Trigger

Stage 1 최소 time trigger:

- configurable daily report time
- timezone 명시
- missed run 시 다음 startup/wake에서 한 번 catch-up
- 같은 날짜 duplicate 생성 방지

general trigger engine 전체를 Stage 1에서 만들지 않는다.

이 trigger는 특정 생활 assistant scheduler가 아니라 control-plane 자체 운영보고용 system trigger다.

## Access

기존 authenticated Web에 read-only endpoint 추가:

- `GET /api/reports/latest`
- `GET /api/reports?from=&to=`

dashboard에 latest report를 보여주는 작은 read-only section은 허용.

새 chat/control UX는 Stage 2.

## Delivery

Stage 1 필수는 durable 생성 + authenticated retrieval.

Discord push/email 등 proactive delivery channel은 Stage 2/3에서 추가 가능.

## 테스트

- scheduled period 한 번 생성
- restart catch-up
- duplicate prevention
- auth 없으면 report API 401
- user A/B isolation 준비
- report generation failure가 researcher loop를 죽이지 않음

## 완료조건

AWS가 매일 report를 durable 생성하고 기존 Web auth를 통해 조회 가능.
