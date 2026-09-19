# 05C — User-Owned Priority Policy

## Status

- 상태: **선행작업 대기**
- 선행조건: 01 Durable Queue + 02 Researcher Loop
- 지금 시작 가능: **아니오**

## 목적

autonomous background work가 사용자 실제 commitment를 방해하지 않게 하되 학교/대회 같은 domain 이름을 core에 하드코딩하지 않는다.

## 수정 파일

- 새 파일: `src/all_tomorrow/priority_policy.py`
- 수정: `src/all_tomorrow/scheduler.py`
- 수정: `src/all_tomorrow/work.py`
- 새 테스트: `tests/test_priority_policy.py`

## 입력

Work metadata에서:

- origin: user / researcher / system
- explicit priority
- commitment_level optional
- urgency/deadline optional
- interruptibility
- resource class

commitment_level 후보:

- hard_commitment
- normal_request
- low_commitment_idea

이 값은 ingress/researcher가 맥락에서 생성할 수 있고 provenance를 가진다.

학교 수행평가/AI 대회라는 문자열 자체를 policy condition으로 사용하지 않는다.

## 현재 사용자 정책

- hard_commitment user Work → P0/P1, background researcher yield
- normal user request → active project 수준
- low_commitment_idea → 바로 실행 필수 아님, Goal/TODO candidate 가능
- autonomous research → 기본 P4 이하

정확한 priority는 deadline/resource context로 조정 가능.

## Yield

현재 실행 중 Work가 interruptible이고 더 높은 priority pending Work가 있으면:

- safe boundary에서 heartbeat/lease 반환 또는 WAITING/PENDING transition
- `work.yielded` Event
- user Work claim 가능

외부 side effect 중간인 non-interruptible Work를 kill해서 corruption 만들지 않는다.

## 테스트

- hard commitment가 research보다 우선
- low-commitment idea가 자동 P0 아님
- domain string 없이 metadata로 동작
- non-interruptible mutation은 safe boundary까지 기다림
- yield 후 background Work provenance/재개 가능

## 완료조건

user-owned high-priority Work가 autonomous work를 실제 queue level에서 밀어내고, low commitment는 즉시 전체 자원을 점유하지 않음.
