BEGIN;

CREATE TABLE IF NOT EXISTS delivery_records (
    delivery_id text PRIMARY KEY,
    kind text NOT NULL,
    subject_refs jsonb NOT NULL DEFAULT '{}'::jsonb,
    destination_adapter text NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    idempotency_scope text NOT NULL DEFAULT 'global',
    retention_class text NOT NULL DEFAULT 'standard',
    valid_until timestamptz,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL CHECK (status IN ('PENDING', 'DISPATCHING', 'DELIVERED', 'AMBIGUOUS', 'FAILED', 'REPAIR_REQUIRED', 'CANCELLED')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    last_error jsonb,
    next_attempt_at timestamptz,
    delivered_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_delivery_status_next_attempt
    ON delivery_records (status, next_attempt_at)
    WHERE status IN ('PENDING', 'DISPATCHING', 'AMBIGUOUS');

CREATE INDEX IF NOT EXISTS idx_delivery_valid_until
    ON delivery_records (valid_until);

CREATE INDEX IF NOT EXISTS idx_delivery_subject_refs
    ON delivery_records USING gin (subject_refs);

COMMIT;
