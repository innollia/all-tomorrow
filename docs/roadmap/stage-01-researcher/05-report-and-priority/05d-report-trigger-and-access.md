# 05D — Report Trigger and Minimal Access

## Status

- 상태: **선행작업 대기**
- 선행조건: 05A + 05B + 04D
- 지금 시작 가능: **아니오**
- contracts: ../../failure-recovery-contract.md

## 목적

Stage 2 전에도 report를 정확한 logical day/time semantics로 생성하고 authenticated read-only access를 제공한다.

## Time model

config:

- IANA timezone
- local report boundary time
- misfire policy
- catch-up horizon
- projection_version

logical_period_id는 local calendar date + timezone + report boundary policy version으로 만든다.
UTC timestamp만으로 "하루" identity를 만들지 않는다.

## Trigger semantics

- duplicate fire → same logical_period_id/idempotency key
- restart 시 missed period를 misfire policy에 따라 catch-up
- 여러 날 offline이면 catch-up horizon 밖 period를 무제한 생성하지 않음
- DST fold/gap에서도 logical period 중복 금지
- 이미 FINAL인 same watermark report를 duplicate 생성하지 않음
- late source면 05A revision semantics 사용
- report failure가 researcher loop를 죽이지 않음

general trigger engine 전체는 Stage 3로 미룸.

## Access

authenticated read-only:

- latest
- range/list
- specific report/revision

authorization:

- user scope isolation
- report source ref fetch도 원본 access scope 준수
- auth 없으면 401
- 다른 user report ID 추측으로 조회 불가

## Requirements

- normal schedule
- restart catch-up
- multi-day offline horizon
- DST fold/gap fixture
- duplicate trigger
- FINAL revision behavior
- auth/user isolation
- generation failure isolation

## 완료조건

실제 AWS restart/time boundary에서도 period당 의도한 report revision만 생성되고 authenticated owner만 조회 가능해야 한다.
