# 04E — Laptop Approval Authority

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 03 + 04D security boundary
- contracts: ../../data-security-artifact-contract.md

## 목적

protected self-change를 AWS가 credential/DB 조작으로 우회할 수 없는 별도 laptop authority로 적용한다.

## Credential boundary

AWS가 보유하지 않음:

- approval signing/auth secret
- authority DB write credential
- protected deployment/apply credential
- authority code/config write 권한

일반 self-modification credential로 이 영역에 write 불가.

## Auth/session

laptop-only HTTPS/Web UI 또는 loopback-trusted UI.

- designated account login
- 승인마다 reauthentication
- password 사용 시 production-grade KDF/hash + salt
- secure/HttpOnly/SameSite session cookie
- CSRF token/origin validation
- session rotation/logout/revocation
- rate limit/backoff for auth attempts
- plaintext credential 저장 금지

CLI/API/Discord approval endpoint를 만들지 않는다.

## Approval record

exact immutable tuple:

- proposal_id + revision
- candidate artifact hash/version
- baseline hash/version
- requested authority change hash
- evaluation refs
- protection policy version
- authenticated account
- nonce
- issued_at / expires_at
- consumed/revoked state

재사용 가능한 boolean approval row가 아니다.

## Apply model

가능하면 laptop authority가 protected apply capability 자체를 소유한다.
AWS DB에 approval=true만 써서 AWS가 protected credential로 적용하는 구조는 피한다.

apply 직전 candidate hash와 request hash를 다시 검증한다.

## Threat-model acceptance

필수 negative scenarios:

1. AWS credential만으로 apply
2. approval DB/row 위조
3. nonce replay
4. expired approval
5. candidate artifact substitution
6. 승인 후 proposal mutation
7. stolen authenticated session + no reauth
8. CSRF/cross-origin request
9. wrong account/password
10. authority file/secret에 normal self-mod credential write
11. laptop offline
12. consumed approval 재사용

모두 protected apply 실패가 관측되어야 한다.

## Audit

저장:

- proposal/revision/hash
- approve/reject
- authenticated account id
- timestamp
- nonce state
- apply result ref

secret/session/password 자체 저장 금지.

## 완료조건

AWS application을 악의적으로 수정한 fixture에서도 laptop authority의 fresh reauth + exact unexpired artifact-bound approval 없이는 protected production change가 불가능해야 한다.
