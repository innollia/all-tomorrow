-- 01A — Semantic Schema Migration (Stage 1.1)
--
-- Goal/Work/Run semantic state를 durable backend queue/checkpoint schema 복제 없이 추가한다.
-- 기존 0001~0005 migration은 과거 사실로 유지하고, 이 파일은 forward-only 변경이다.
-- 레거시 `tasks`/pipeline `runs` 테이블은 보존한다(기존 row identity/provenance 유지).
--
-- 불변식 (domain/state.py, tests/test_architecture_fitness.py와 일치):
--   * Work는 execution_backend/execution_id/execution_version을 갖지 않는다.
--     External execution linkage는 Run이 소유한다.
--   * Work 1:N Run.
--   * Run에는 최대 하나의 active logical ExecutionRef.
--   * runs_semantic.trace_id에 UNIQUE 제약을 두지 않는다.
--   * All Tomorrow queue authority 목적의 claimed_by / lease_expires_at /
--     backend retry bookkeeping column을 두지 않는다.

BEGIN;

-- ---------------------------------------------------------------------------
-- goals — 사용자·프로젝트 의미의 최상위 목표
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS goals (
    goal_id text PRIMARY KEY,
    user_id text NOT NULL,
    project_id text REFERENCES projects(project_id),
    title text NOT NULL,
    objective text,
    semantic_status text NOT NULL DEFAULT 'ACTIVE'
        CHECK (semantic_status IN (
            'ACTIVE', 'WAITING', 'SUCCEEDED', 'FAILED',
            'CANCEL_REQUESTED', 'CANCELLED'
        )),
    priority integer NOT NULL DEFAULT 0,
    origin text,
    commitment text NOT NULL DEFAULT 'default',
    completion_policy_ref text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    terminal_at timestamptz
);

CREATE INDEX IF NOT EXISTS goals_user_status_idx
    ON goals (user_id, semantic_status);

-- ---------------------------------------------------------------------------
-- work_items — Goal 아래 실행 의미 단위 (기존 tasks의 semantic 후계)
--   CRITICAL: execution_backend / execution_id / execution_version 컬럼 없음.
--   external execution linkage는 runs_semantic가 소유한다.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS work_items (
    work_id text PRIMARY KEY,
    goal_id text NOT NULL REFERENCES goals(goal_id),
    user_id text NOT NULL,
    project_id text REFERENCES projects(project_id),
    title text NOT NULL,
    semantic_status text NOT NULL DEFAULT 'PENDING'
        CHECK (semantic_status IN (
            'PENDING', 'RUNNING', 'WAITING', 'SUCCEEDED', 'FAILED',
            'CANCEL_REQUESTED', 'CANCELLED'
        )),
    priority integer NOT NULL DEFAULT 0,
    origin text,
    trace_id text,
    payload_ref text,
    wait_reason text,
    parent_work_id text REFERENCES work_items(work_id),
    lineage_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    terminal_at timestamptz
);

CREATE INDEX IF NOT EXISTS work_items_goal_idx
    ON work_items (goal_id);
CREATE INDEX IF NOT EXISTS work_items_status_priority_idx
    ON work_items (semantic_status, priority DESC);

-- ---------------------------------------------------------------------------
-- runs_semantic — Work의 한 logical execution attempt.
--   Work 1:N Run. ExecutionRef(backend/id/version)는 여기(Run)에만 존재.
--   backend internal status/schema는 복제하지 않는다.
--   trace_id는 조회용이며 UNIQUE 제약을 두지 않는다.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs_semantic (
    run_id text PRIMARY KEY,
    work_id text NOT NULL REFERENCES work_items(work_id),
    semantic_status text NOT NULL DEFAULT 'STARTING'
        CHECK (semantic_status IN (
            'STARTING', 'RUNNING', 'WAITING', 'SUCCEEDED', 'FAILED',
            'CANCEL_REQUESTED', 'CANCELLED'
        )),
    attempt_number integer NOT NULL DEFAULT 1 CHECK (attempt_number >= 1),
    attempt_origin text,
    attempt_reason text,
    -- ExecutionRef (Run 소유, nullable — attach 전에는 비어 있음)
    execution_backend text,
    execution_id text,
    execution_version integer CHECK (execution_version IS NULL OR execution_version >= 1),
    trace_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision >= 1),
    started_at timestamptz,
    terminal_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS runs_semantic_work_idx
    ON runs_semantic (work_id);
CREATE INDEX IF NOT EXISTS runs_semantic_trace_idx
    ON runs_semantic (trace_id)
    WHERE trace_id IS NOT NULL;

-- 하나의 Work에 최대 하나의 active Run만 허용 (Work 1:N Run + single active attempt)
CREATE UNIQUE INDEX IF NOT EXISTS one_active_run_per_work
    ON runs_semantic (work_id)
    WHERE semantic_status IN ('STARTING', 'RUNNING', 'WAITING', 'CANCEL_REQUESTED');

-- ---------------------------------------------------------------------------
-- outcomes — CompletionEvidence / OutcomeRecord persistence
--   Work/Goal SUCCEEDED transition은 outcome/evidence linkage를 가져야 한다.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id text PRIMARY KEY,
    target_type text NOT NULL
        CHECK (target_type IN ('GOAL', 'WORK', 'RUN', 'EXPERIMENT', 'DEPLOYMENT')),
    target_id text NOT NULL,
    status text NOT NULL
        CHECK (status IN ('SATISFIED', 'NOT_SATISFIED', 'INCONCLUSIVE')),
    criterion_ref text,
    criterion_version text,
    evaluator_ref text,
    evaluator_version text,
    observed_values jsonb NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    artifact_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS outcomes_target_idx
    ON outcomes (target_type, target_id);

-- SATISFIED outcome은 criterion+evaluator linkage를 반드시 가진다
-- (domain: OutcomeStatus.SATISFIED requires CompletionEvidence).
ALTER TABLE outcomes DROP CONSTRAINT IF EXISTS outcomes_satisfied_requires_evidence;
ALTER TABLE outcomes ADD CONSTRAINT outcomes_satisfied_requires_evidence
    CHECK (
        status <> 'SATISFIED'
        OR (criterion_ref IS NOT NULL AND evaluator_ref IS NOT NULL)
    );

-- ---------------------------------------------------------------------------
-- questions_semantic — canonical Question lifecycle
--   기존 user_questions(레거시 pipeline)와 별개로 canonical contract를 둔다.
--   status: PENDING / ANSWERED / SUPERSEDED / CANCELLED / EXPIRED
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS questions_semantic (
    question_id text PRIMARY KEY,
    work_id text REFERENCES work_items(work_id),
    run_id text REFERENCES runs_semantic(run_id),
    prompt text NOT NULL,
    status text NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'ANSWERED', 'SUPERSEDED', 'CANCELLED', 'EXPIRED')),
    answer_ref text,
    signal_correlation text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz,
    expires_at timestamptz
);

CREATE INDEX IF NOT EXISTS questions_semantic_work_idx
    ON questions_semantic (work_id)
    WHERE work_id IS NOT NULL;

-- Work당 최대 하나의 PENDING question
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_question_per_work
    ON questions_semantic (work_id)
    WHERE status = 'PENDING' AND work_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- semantic_events — Goal/Work/Run provenance (Run 정리와 cascade 소실 안 함)
--   0001 events는 레거시 run FK에 ON DELETE CASCADE가 걸려 있으므로,
--   semantic provenance는 별도 테이블에 두고 run 삭제와 독립 보존한다.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS semantic_events (
    event_id text PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    goal_id text,
    work_id text,
    run_id text,
    trace_id text,
    external_ref text,
    actor text NOT NULL,
    type text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    artifact_refs jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS semantic_events_goal_idx
    ON semantic_events (goal_id, occurred_at)
    WHERE goal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS semantic_events_work_idx
    ON semantic_events (work_id, occurred_at)
    WHERE work_id IS NOT NULL;

COMMIT;
