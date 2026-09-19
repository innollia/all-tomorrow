# 00A-5 — Selection Record

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 00A-2 + 00A-3 + 00A-4

## 목적

기능표가 아니라 실제 failure experiment 결과로 production substrate 조합을 하나 잠근다.

## Durable Hard Gates

DBOS/Restate 각각:

- Python 3.13
- personal AWS self-host
- crash/restart recovery
- deterministic duplicate-start
- durable user wait/signal
- long timer/delay
- cancel
- external-side-effect idempotency/reconciliation seam
- Goal/Work state와 backend state 분리
- ordinary upgrade에서 in-flight recovery 전략
- durable journal payload/retention/backup/encryption 설명 가능
- privacy-safe OTel propagation

하나라도 필수 gate가 실패하면 기본 durable backend로 선택하지 않는다.

## Durable Tie-break

둘 다 gate를 통과했을 때만:

1. persistent service/process 수
2. custom glue/adapter LOC
3. failure semantics inspectability
4. 향후 AWS + laptop + executor 확장에서 paid/proprietary control plane 강제 여부
5. backup/restore와 local reproduction
6. upgrade ceremony

dashboard/기능 개수는 기준이 아니다.

## Gateway Decision

00A-4의 G01~G12를 기준으로 LiteLLM MCP 또는 FastMCP fallback을 선택한다.

gateway 결과는 durable candidate 점수와 분리한다.

## Final Compatibility Run

선택된 durable backend + 선택된 gateway + LiteLLM model gateway를 함께 연결한다.

최종으로 확인:

- normal agent run
- tool discovery/call
- kill/restart
- user wait/resume
- external mutation crash/reconciliation
- gateway restart
- model gateway temporary failure
- in-flight run을 남긴 채 ordinary dependency/app upgrade
- OTel correlation
- canary privacy scan

이 조합에서만 나타나는 문제는 durable/gateway 어느 쪽 단독 실패로 소급하지 말고 integration issue로 기록한다.

## Production Pin

선택 후에만 root production dependency/container pin을 작성한다.

- exact package versions
- immutable image tag/digest
- no mutable latest
- Dependabot PR 허용
- substrate dependency auto-merge 금지
- upgrade PR은 D01~D12 + G01~G12 관련 regression을 통과

## Stage 1 Rewrite Inputs

00E가 Stage 1을 재작성할 수 있도록 다음을 넘긴다.

- selected durable backend
- selected gateway
- DurableExecutionPort mapping
- persisted naming/versioning rules
- retry ownership matrix
- process topology
- data retention/security boundary
- migration triggers
- rejected custom mechanisms
