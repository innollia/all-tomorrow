# 04D — AWS Always-On Runtime

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01A~01C durable state/queue + 04A LiteLLM Gateway
- 04B/04C와 병렬 가능: 부분적

## 목적

AWS를 항상 켜진 researcher 중앙 runtime으로 사용한다.

2차의 full remote assistant UI까지 여기서 만들지 않는다.

## 초기 process 구성

AWS host에서 최소:

1. PostgreSQL
2. All Tomorrow researcher/control service
3. LiteLLM Proxy

repo mutation worker는 AWS에서 실행하지 않아도 됨. Stage 1 repo mutation은 laptop executor가 담당.

## 추가 파일 계획

- 새 디렉터리: `deploy/systemd/`
- service unit example:
  - all-tomorrow.service
  - litellm.service 또는 container wrapper
- 새 파일: `deploy/README.md`
- 수정: `.env.example`

Docker/Kubernetes를 필수로 만들지 않는다. 현재 AWS Ubuntu host에서 단순 service supervision을 우선한다.

## All Tomorrow service 책임

- DB connection open/migrate는 deploy command에서 명시적으로 수행
- durable Work claim loop
- researcher wake trigger
- model/API research work
- daily report materialization
- health/readiness

Web의 full user control surface는 Stage 2.

Stage 1에서는 최소 admin/health endpoint가 있어도 되지만 새 dashboard를 만들지 않는다.

## Crash behavior

service restart:

- process memory queue에 의존하지 않음
- claimed Work lease 만료 후 recovery
- open Goal/Work 보존
- Run/Question 보존

startup 시 무조건 모든 expired Work를 재실행하지 말고 queue recovery primitive만 수행한다.

## Secret placement

AWS secret/environment에:

- PostgreSQL DSN
- LiteLLM access key
- provider keys는 가능하면 LiteLLM 쪽에서 소유

Event/DB에 raw key 저장 금지.

## Laptop executor 연결

Stage 1에서 필요한 것은 interface boundary까지만.

AWS Work가 repo mutation을 요구하면 laptop executor가 offline일 경우 Work를 잃지 않고 WAITING/PENDING 상태로 남길 수 있어야 한다.

multi-host workspace sync는 만들지 않는다.

## 운영 확인

- service restart
- host reboot
- PostgreSQL reconnect
- LiteLLM unavailable → Work/Run 실패 observation
- laptop offline → repo Work 보류
- researcher non-repo work는 AWS에서 계속 가능

## 하지 말 것

- Kubernetes
- multi-region
- HA cluster
- Stage 2 full Web chat
- AWS가 laptop Approval Authority 역할 겸임
- AWS에 protected approval signing secret 복사

## 완료조건

1. AWS reboot 뒤 durable state 유지
2. researcher wake/queue가 다시 진행
3. laptop offline이 중앙 state 유실로 이어지지 않음
4. LiteLLM/DB health가 관찰 가능
