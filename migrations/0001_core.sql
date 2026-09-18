BEGIN;

CREATE TABLE IF NOT EXISTS projects (
    project_id text PRIMARY KEY,
    name text NOT NULL,
    owner text NOT NULL,
    source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_versions (
    pipeline_id text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    status text NOT NULL CHECK (status IN ('draft', 'active', 'retired')),
    parent_version integer,
    change_reason text,
    spec jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pipeline_id, version),
    FOREIGN KEY (pipeline_id, parent_version)
        REFERENCES pipeline_versions (pipeline_id, version)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_pipeline_version
    ON pipeline_versions (pipeline_id)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS tasks (
    task_id text PRIMARY KEY,
    project_id text REFERENCES projects(project_id),
    title text NOT NULL,
    status text NOT NULL,
    priority integer NOT NULL DEFAULT 2 CHECK (priority BETWEEN 0 AND 6),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    run_id text PRIMARY KEY,
    request_id text NOT NULL,
    trace_id text NOT NULL,
    user_id text NOT NULL,
    project_id text REFERENCES projects(project_id),
    session_id text,
    task_id text REFERENCES tasks(task_id),
    pipeline_id text NOT NULL,
    pipeline_version integer NOT NULL,
    status text NOT NULL,
    current_step_id text NOT NULL,
    context jsonb NOT NULL,
    outputs jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempts jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text,
    revision bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (trace_id),
    FOREIGN KEY (pipeline_id, pipeline_version)
        REFERENCES pipeline_versions (pipeline_id, version)
);

CREATE INDEX IF NOT EXISTS runs_project_updated_idx
    ON runs (project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS run_steps (
    run_id text NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    step_id text NOT NULL,
    attempt integer NOT NULL CHECK (attempt > 0),
    status text NOT NULL,
    input jsonb,
    output jsonb,
    error text,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    PRIMARY KEY (run_id, step_id, attempt)
);

CREATE TABLE IF NOT EXISTS events (
    event_id text PRIMARY KEY,
    occurred_at timestamptz NOT NULL,
    user_id text,
    project_id text,
    session_id text,
    trace_id text NOT NULL,
    run_id text REFERENCES runs(run_id) ON DELETE CASCADE,
    actor text NOT NULL,
    type text NOT NULL,
    parent_event_id text REFERENCES events(event_id),
    input_ref text,
    output_ref text,
    artifact_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS events_trace_time_idx
    ON events (trace_id, occurred_at, event_id);

CREATE INDEX IF NOT EXISTS events_project_time_idx
    ON events (project_id, occurred_at DESC)
    WHERE project_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS user_questions (
    question_id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    blocked_step text NOT NULL,
    question text NOT NULL,
    reason text NOT NULL,
    required_fields jsonb NOT NULL,
    resume_token_hash text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('pending', 'answered', 'cancelled', 'expired')),
    answer jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz,
    expires_at timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS one_pending_question_per_run
    ON user_questions (run_id)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS capabilities (
    capability_id text PRIMARY KEY,
    description text NOT NULL
);

CREATE TABLE IF NOT EXISTS workers (
    worker_id text PRIMARY KEY,
    status text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tools (
    tool_id text PRIMARY KEY,
    provider text NOT NULL,
    risk text NOT NULL,
    permissions jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS registry_bindings (
    subject_type text NOT NULL CHECK (subject_type IN ('worker', 'tool')),
    subject_id text NOT NULL,
    capability_id text NOT NULL REFERENCES capabilities(capability_id),
    PRIMARY KEY (subject_type, subject_id, capability_id)
);

COMMIT;

