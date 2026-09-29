-- 0007 -- Feature 11: durable request idempotency (Stage 2.1A persisted to Postgres).
--
-- The in-memory RequestStore (requests.py) dedupes within one process's lifetime
-- only. This table persists the (user_id, namespace, version, value) -> request_id
-- mapping and the Request/Delivery rows themselves so a client retry after a
-- server restart still collapses to the SAME Request instead of creating a
-- duplicate Goal.

BEGIN;

CREATE TABLE IF NOT EXISTS idempotent_requests (
    request_id text PRIMARY KEY,
    user_id text NOT NULL,
    text text NOT NULL,
    attachment_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    user_id text NOT NULL,
    namespace text NOT NULL,
    key_version text NOT NULL,
    value text NOT NULL,
    request_id text NOT NULL REFERENCES idempotent_requests(request_id),
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, namespace, key_version, value)
);

CREATE TABLE IF NOT EXISTS idempotent_deliveries (
    delivery_id text PRIMARY KEY,
    request_id text NOT NULL REFERENCES idempotent_requests(request_id),
    ingress text NOT NULL,
    source_event_id text NOT NULL,
    namespace text NOT NULL,
    key_version text NOT NULL,
    value text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idempotent_deliveries_request_idx
    ON idempotent_deliveries (request_id);

COMMIT;
