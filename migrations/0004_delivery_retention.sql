BEGIN;

-- 0004_delivery_retention.sql: Safely alter existing delivery_records table and backfill TTLs

ALTER TABLE delivery_records
    ADD COLUMN IF NOT EXISTS idempotency_scope text NOT NULL DEFAULT 'global',
    ADD COLUMN IF NOT EXISTS retention_class text NOT NULL DEFAULT 'standard',
    ADD COLUMN IF NOT EXISTS valid_until timestamptz;

-- Backfill existing rows that have NULL valid_until and standard retention
UPDATE delivery_records
SET valid_until = created_at + INTERVAL '24 hours'
WHERE valid_until IS NULL AND retention_class = 'standard';

CREATE INDEX IF NOT EXISTS idx_delivery_valid_until
    ON delivery_records (valid_until);

COMMIT;
