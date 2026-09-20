# 04D — AWS Single-Node Runtime

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 + 01 durable bridge + 04A
- contracts: ../../failure-recovery-contract.md, ../../data-security-artifact-contract.md

## 목적

AWS를 항상 켜진 researcher 중앙 runtime으로 실제 배치하고 reboot/deploy/backup/secret 경계를 검증한다.

## Topology

00E에서 확정한 최소 process topology를 문서와 IaC/service config로 고정한다.

최소 logical services:

- All Tomorrow application
- application PostgreSQL
- selected durable runtime/state
- LiteLLM Proxy
- selected tool gateway if separate
- OTel exporter/collector if selected

## Deployment contract

각 service에 명시:

- package/image/binary exact version
- process supervisor/autostart
- bind address/port
- inbound/outbound network policy
- health/readiness probe
- persistent volume/path
- secret injection source
- log destination/retention
- restart policy
- deployment/update command
- rollback command/version

mutable latest 금지.

## Network/security

- public surface는 필요한 HTTPS ingress만
- PostgreSQL/durable/gateway admin ports는 private/local security group
- TLS termination과 certificate renewal owner
- AWS runtime에 laptop approval secret/protected deployment credential 없음
- IAM/security group 최소권한 inventory

## Persistence / backup

application DB, durable state, gateway persistent state(사용 시)를 별도 owner로 기록.

각각:

- backup mechanism
- schedule
- retention
- restore procedure
- restore verification fixture
- application/durable state를 단일 transaction-consistent backup이라고 가정하지 않음

restore 후 cross-store reconciliation으로 semantic Run identity를 회복할 수 있어야 한다.

## Failure scenarios

- service process restart
- whole instance reboot
- LiteLLM unavailable
- durable runtime restart
- PostgreSQL restart
- disk/persistent state remount
- laptop offline
- deploy V1→V2 + in-flight Run
- backup restore to test environment

## Requirements

| ID | 요구 | Level |
|---|---|
| 04D-01 reboot 뒤 in-flight recovery | L3 |
| 04D-02 model/tool gateway failure가 Goal 유실 안 함 | L3 |
| 04D-03 laptop offline → durable wait | L3 |
| 04D-04 protected credential AWS 부재 | L3 security |
| 04D-05 backup→restore 후 domain + reconciliation | L3 |
| 04D-06 health/readiness와 supervisor actual behavior | L3 |
| 04D-07 deploy/rollback runbook 재현 | L3 |

## 완료조건

AWS single-node를 실제 재부팅/복원/업그레이드해도 semantic state가 유지되고 모든 service/secret/backup/rollback 책임이 문서와 실제 설정에서 일치해야 한다.
