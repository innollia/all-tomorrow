# Operations, Security & Compatibility Contract

## Secret management

deployment마다 secret owner를 명시한다.

AWS:
- preferred secret backend를 00E/04D에서 하나 확정
- application IAM/role은 필요한 secret만 read
- approval/protected deployment secret은 AWS에 존재하지 않음

Laptop:
- Approval Authority secret store 별도
- ordinary worker environment와 credential domain 분리

모든 secret은:
- secret_id/ref만 domain에 저장
- rotation/revocation procedure
- reload/restart behavior
- last-rotated metadata
- access audit
를 가진다.

raw secret를 config example, Event, Artifact metadata, log에 저장하지 않는다.

## Prompt / policy versions

prompt/config/policy는 mutable filename이 아니라 immutable version/hash ref로 실행 provenance에 연결한다.

최소:
- prompt_id
- version/hash
- source commit/artifact ref
- created_by
- protection class
- supersedes
- active alias optional

promotion/rollback은 alias/ref switch로 표현한다.

## Prompt-injection / untrusted content

다음 content는 instruction authority가 없는 untrusted evidence로 취급한다.

- retrieved web page
- external repository README/issues
- uploaded documents
- tool output
- artifact text
- emails/messages not explicitly authenticated as control input

ContextPack은 data content와 control instructions를 구분해 provenance/authority metadata를 전달한다.
untrusted text 안의 "system", "run command", "ignore policy" 같은 지시로 authority/tool permission을 확대하지 않는다.

## DB migration / mixed version

production migration은 expand/contract를 기본으로 한다.

- Vn과 Vn+1 app이 동시에 읽을 수 있는 expand phase
- code switch/drain
- contract cleanup
- irreversible migration은 automatic ordinary promotion 금지 또는 protected migration plan 요구
- rollback 가능성/backup dependency 명시

migration ID/schema version은 persisted compatibility data다.

## API versioning

public/internal remote API는 versioned schema를 가진다.

- API version
- request/response model version
- idempotency semantics
- deprecation window
- unknown field behavior
- old client behavior
- compatibility tests

breaking change는 old client fixture 없이 merge하지 않는다.

## Audit tamper boundary

Event/audit table에 대해 ordinary application path는 append-only를 기본으로 한다.

- UPDATE/DELETE privilege 분리 또는 application code에서 금지
- maintenance purge는 별도 privileged operation + audit evidence
- critical approval/deploy Event는 immutable artifact/hash 또는 external log sink로 integrity evidence를 남길 수 있음

self-modifying ordinary credential이 과거 approval/audit evidence를 조용히 변경할 수 없어야 한다.

## SLO / alerts

최소 operational signals:

- STARTING/no-ref reconciliation stuck
- Delivery REPAIR_REQUIRED
- repeated Run failure/replan storm
- budget/resource exhausted
- backup failed/stale
- durable backend unavailable
- model/tool gateway unavailable
- approval/auth attack threshold
- report/trigger missed
- disk/storage pressure

각 signal:
- metric/query
- threshold/window
- severity
- notification destination
- runbook/ref

Stage 1에서는 최소 alert path 하나를 실제 검증한다.

## Dependency security

exact pin/Dependabot 외:

- dependency vulnerability scan
- SBOM artifact
- license inventory/policy
- lockfile integrity
- container/image digest
- update PR source/provenance
- high-risk install/build script review/sandbox

security update도 durable replay/compatibility test를 우회하지 않는다.

## Outbound / proactive channel security

proactive channel adapter는:
- authenticated account/channel binding
- destination ownership verification
- message idempotency
- secret/sensitive content policy
- provider failure/retry
- opt-out/disable
를 가진다.
