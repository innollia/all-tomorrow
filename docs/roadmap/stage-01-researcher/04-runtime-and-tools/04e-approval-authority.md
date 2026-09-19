# 04E — Laptop Approval Authority

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 1.3 Evaluation & Self-Improvement
- ADR: `../../decisions/0004-self-modification-and-approval-boundary.md`

## 목적

protected self-change를 AWS 본체가 구조적으로 우회할 수 없게 노트북에 별도 authority를 둔다.

## 보안 경계

AWS All Tomorrow는 보유하지 않음:

- approval signing secret
- approval DB write credential
- protected deployment credential
- Approval Authority code/data write 권한

일반 All Tomorrow self-modification credential로 이 영역을 수정할 수 없어야 한다.

## 승인 UI

노트북에서만 노출되는 Web UI.

조건:

1. 지정 사용자 계정 로그인
2. 승인 버튼마다 재인증
3. 다른 Web/API/Discord/CLI ingress에서 승인 불가
4. password를 쓰면 production-grade password KDF/hash 사용
5. plaintext password 저장 금지

## Proposal input

Approval Authority가 받는 것은 raw arbitrary command가 아니라:

- proposal_id
- protected boundary diff summary
- exact artifact/version/hash
- evaluation evidence refs
- requested authority change
- expiry/nonce

승인 결과는 그 exact proposal/version에만 유효.

승인 후 proposal 내용이 바뀌면 재승인 필요.

## Apply model

가능하면 Approval Authority가 "승인=true" boolean만 AWS DB에 써주는 구조보다, protected deploy/apply에 필요한 capability 자체를 소유한다.

즉 AWS는 approval row를 위조해도 protected change를 적용할 credential이 없어야 한다.

## 감사

저장:

- proposal identity
- approved/rejected
- authenticated account id
- timestamp
- artifact hash/version

저장 금지:

- password
- session secret
- signing secret

## 테스트

- AWS credential만으로 protected apply 실패
- 로그인만 된 session으로 승인 실패, 재인증 필요
- wrong password 실패
- other account 실패
- CLI/API approval endpoint 없음
- proposal hash 변경 후 old approval 무효
- replay 방지
- laptop offline일 때 proposal은 pending

## 하지 말 것

- AWS fallback approval
- emergency master password를 AWS에 복사
- Discord 승인
- generic agent가 approval UI를 대신 클릭
- self-modifying code와 approval secret을 같은 credential domain에 두기

## 완료조건

AWS 본체를 임의로 수정한 test fixture에서도 protected change를 laptop authority 없이 production에 적용할 수 없음.
