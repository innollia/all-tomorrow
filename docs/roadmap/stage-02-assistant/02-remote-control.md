# Stage 2.2 — Remote Control Surface

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 2.1 + Stage 1 runtime
- 지금 시작 가능: **아니오**
- contracts: ../data-security-artifact-contract.md, ../failure-recovery-contract.md

## 목적

AWS central runtime을 어느 기기에서나 안전하게 접근 가능한 authenticated control surface로 만든다. UI memory/WebState가 authority가 아니라 PostgreSQL-backed domain state가 authority다.

## Public surface

HTTPS only:

- login/logout/session management
- create Request
- Goal/Work/Run read
- cancel Work/Run request
- pending Question read/answer
- Artifact/result metadata + authorized download
- report read
- health는 public 최소 정보, readiness/admin은 restricted

## Authentication/session contract

- production password KDF 또는 external auth provider
- Secure + HttpOnly + SameSite cookie
- CSRF protection
- session rotation on login/reauth
- absolute + idle expiry
- logout/revocation
- per-account active session list/revoke capability
- brute-force/rate limit
- auth/audit Event
- raw password/session secret log 금지

authorization은 user/project/source scope를 모든 object fetch/mutation에 적용한다. object ID 추측으로 cross-user access가 불가해야 한다.

## Store-backed UI

Web request lifecycle:

HTTP
→ authenticated user/session
→ canonical Request/Delivery
→ Goal/Work/Run
→ Question/Artifact/report projection

prototype in-memory WebState는 cache/view helper 이상 authority가 될 수 없다.

## Restart

app restart/session policy:

- durable Work/Question state 유지
- session store strategy 명시
- in-flight request response가 끊겨도 client idempotency key로 재조회/retry 가능
- reconnect가 duplicate Request를 만들지 않음

## Backup/restore

Stage 1 AWS backup contract를 remote surface까지 검증한다.

명시:

- RPO target
- RTO test target
- application DB / durable backend / artifact metadata owner별 backup
- restore sequence
- cross-store reconciliation
- restored environment에서 auth/session secret rotation 여부
- backup artifact access control/retention

숫자 target은 deployment config/ADR에 실제 값으로 적고 미정인 채 완료하지 않는다.

## Requirements

| ID | 요구 | Level |
|---|---|
| 2.2-01 remote HTTPS login→Request→result | L3 |
| 2.2-02 CSRF/session fixation/revocation tests | L1/L3 |
| 2.2-03 cross-user object access 실패 | L1/L3 |
| 2.2-04 restart 후 same Request/Question continuity | L3 |
| 2.2-05 client retry duplicate 없음 | L3 |
| 2.2-06 backup restore 후 domain/reconciliation | L3 |
| 2.2-07 RPO/RTO 실제 측정 | L3 |

## 완료조건

노트북 밖 기기에서 안전하게 동일 중앙 state를 조작하고 restart/restore 뒤에도 canonical identity가 유지되어야 한다.
