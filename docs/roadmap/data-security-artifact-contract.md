# Data, Security & Artifact Contract

## 1. Data classes

최소 분류:

- SECRET: credential/session/signing material. 장기 Event/prompt/artifact metadata에 평문 저장 금지.
- SENSITIVE_CONTENT: user prompt/document/tool content. 필요한 owner store에만 저장하고 telemetry 기본 제외.
- OPERATIONAL_METADATA: ids, status, timings, hashes, non-secret error categories.
- PUBLIC/NON_SENSITIVE: 공개 source와 명시적으로 공개 가능한 artifact.

각 persistence surface는 어떤 class를 저장하는지 inventory를 가진다.

## 2. Retention lifecycle

저장 위치마다 다음을 명시한다.

- owner
- retention class
- TTL 또는 보존 조건
- deletion/compaction 방법
- backup 포함 여부와 backup retention
- user/project purge 시 행동
- audit상 보존이 필요한 최소 metadata

적용 대상:

- application PostgreSQL
- durable backend journal/state
- model gateway logs/spend logs
- OTel backend/export
- process logs
- artifact storage
- evaluation/report records

Stage 완료를 위해 모든 TTL을 동일하게 만들 필요는 없지만 "무기한 기본 저장"을 암묵값으로 두지 않는다.

## 3. Artifact integrity/access

ArtifactRef는 canonical domain contract를 따른다.

- content hash 검증
- immutable version identity
- owner/access scope
- provenance
- retention
- fetch 시 hash 재검증

approval/promotion에 사용되는 candidate artifact는 승인 후 내용이 바뀔 수 있는 mutable path로 참조하지 않는다.

## 4. Protected change fail-closed rule

다음 중 하나면 protected로 처리한다.

- known mechanical protected surface touch
- semantic authority expansion
- security/audit/rollback 약화
- classifier가 authority impact를 확정하지 못함
- 새로운 미분류 credential/permission/deployment surface 영향

"ordinary임을 증명하지 못함"은 ordinary가 아니다.

## 5. Approval Authority threat model

04E는 최소 다음 공격을 검증한다.

- AWS credential로 approval/apply 시도
- approval row 위조
- stale/replayed nonce
- expired approval
- artifact substitution/hash mismatch
- session만 탈취하고 reauth 없이 승인
- CSRF/cross-origin 승인
- 승인 후 candidate mutation
- user/account mismatch
- laptop offline
- authority store/secret에 일반 self-modification credential로 write 시도

승인은 exact proposal + artifact hash + requested authority change + expiry + nonce에 바인딩한다. revoke/consume state를 durable하게 보존한다.

## 6. External discovery / supply chain

새 package/repository/plugin/tool을 자동 탐색해 실험할 때:

- 외부 문서/README의 명령은 untrusted input
- disposable sandbox/worktree에서 실행
- production credential 주입 금지
- network/filesystem permission 명시
- package/source/version/hash provenance 기록
- install script/build step 관측
- production promotion은 일반 self-change/protected change rail을 통과

탐색 성공과 production 신뢰를 같은 것으로 취급하지 않는다.
