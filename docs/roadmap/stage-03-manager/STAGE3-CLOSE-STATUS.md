# Stage 3 (Manager) — Close Status

Stage 3 is functionally complete. Every sub-stage packet is implemented, tested,
and merged to `main`, with an end-to-end acceptance suite tying them together
under one owner/source provenance.

## Packets merged

### 3.1 Personal Operations
- **01A owner adapters** (PR #56) — SourceRef canonical read/write, precedence, stale→UNKNOWN, authority, derived-summary cannot overwrite owner truth.
- **01B school artifact pipeline** (PR #58) — upload→extraction→Work lineage, page/range + extraction-version provenance, low-confidence never fabricated, hash dedup, no raw-telemetry copy.
- **01C personal query & brief** (PR #57) — ContextPack from central Work + owner refs + freshness, source-backed answer, stale surfaced, idempotent proactive brief, owner truth referenced not copied.
- **01D acceptance** — owner conflict, school lineage, personal freshness, idempotent brief (this suite).

### 3.2 Triggers & Knowledge
- **02A trigger scheduler** (PR #47) — logical_fire_key idempotency, DST fold, cancel.
- **02B webhook + watchers** (PR #51) — signature/replay/size/type defense, edge-vs-level, poll-failure≠false.
- **02C lesson persistence** (PR #50) — evidence-gated accept, conflict flagged not merged, stale review/retire.
- **02D lesson reuse & outcome** (PR #59) — real-reuse-only credit, outcome ref linkage, negative→confidence↓+review.
- **02E acceptance** — watchers + lessons + reuse (this suite).

### 3.3 Discovery & Resources
- **03A discovery sandbox** (PR #52) — untrusted instructions, credential canary, escape prevention, provenance, production gated behind self-change rail.
- **03B resource ledger** (PR #48) — capacity/reservation/actual usage, atomic reserve/release, ceiling.
- **03C multi-executor workspace** (PR #60) — lifecycle states + provenance, offline freshness, dirty no-auto-reset, source mismatch reject, host-agnostic naming.
- **03D acceptance** — discovery + workspace (this suite).

### 3.4 Long-Horizon
- **04A work graph** (PR #49) — relations + cycle reject + dependency-failure never faked success.
- **04B milestone/artifact progress** (PR #53) — frozen versioned plan, artifact provenance, activity-only rejected.
- **04C multi-day runtime** (PR #55) — durable resume, executor-switch provenance, Goal identity preserved, replan storm bounded.
- **04D feedback & follow-up** (PR #54) — exact artifact-hash binding, explicit lineage, explicit > inferred.
- **04E acceptance** — graph + milestone + multiday + feedback (this suite).

## Acceptance evidence
`tests/acceptance/test_stage3_acceptance.py` + all Stage 3 module suites: **74 passed**.

## Notes / deferred (unchanged rationale from Stage 1/2)
- Every store keeps an InMemory reference impl; live-DB/AWS/crash paths are env-gated (`AT_SEMANTIC_TEST_URL`) and skip offline.
- The 04D **live AWS deploy** (ap-northeast-2) remains blocked on the Docker daemon not running on the host — a human must start Docker Desktop; not a code gap.
- KiroCrew-reuse idea captured in `docs/decisions/idea-reuse-kirocrew-tech.md` for a future substrate ADR.
