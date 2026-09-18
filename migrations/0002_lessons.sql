BEGIN;

CREATE TABLE IF NOT EXISTS lessons (
    lesson_id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES projects(project_id),
    title text NOT NULL,
    body text NOT NULL,
    tags jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('candidate', 'accepted', 'rejected', 'promoted')),
    reuse_count integer NOT NULL DEFAULT 0 CHECK (reuse_count >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lesson_evidence (
    lesson_id text NOT NULL REFERENCES lessons(lesson_id) ON DELETE CASCADE,
    evidence_ref text NOT NULL,
    PRIMARY KEY (lesson_id, evidence_ref)
);

CREATE TABLE IF NOT EXISTS skills (
    skill_id text PRIMARY KEY,
    name text NOT NULL,
    body text NOT NULL,
    status text NOT NULL CHECK (status IN ('candidate', 'evaluating', 'accepted', 'retired')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS skill_evidence (
    skill_id text NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    lesson_id text NOT NULL REFERENCES lessons(lesson_id),
    evaluation_ref text,
    PRIMARY KEY (skill_id, lesson_id)
);

COMMIT;

