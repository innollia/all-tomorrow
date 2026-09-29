-- 0008 -- Device agent: registered devices and Work leases (Tailscale executor).
--
-- Device identity/lease is intentionally separate from the Goal/Work/Run
-- semantic core (work_items keeps no execution_ref/device column — see
-- domain.state.WorkRecord's forbidden-fields invariant and
-- check_semantic_schema_invariants in scripts/check_architecture_fitness.py).
-- A device's claim on a Work is tracked here as a lease row; the Work's own
-- PENDING->RUNNING transition still goes through work_items via the existing
-- claim_pending_work query (FOR UPDATE SKIP LOCKED).

BEGIN;

CREATE TABLE IF NOT EXISTS devices (
    device_id text PRIMARY KEY,
    name text NOT NULL,
    owner_user_id text NOT NULL,
    token_digest text NOT NULL,
    capabilities jsonb NOT NULL DEFAULT '[]'::jsonb,
    max_concurrent integer NOT NULL DEFAULT 1,
    status text NOT NULL DEFAULT 'OFFLINE',
    registered_at timestamptz NOT NULL DEFAULT now(),
    last_heartbeat_at timestamptz,
    revoked_at timestamptz,
    revision integer NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS devices_owner_idx ON devices (owner_user_id);

CREATE TABLE IF NOT EXISTS device_registration_codes (
    code text PRIMARY KEY,
    owner_user_id text NOT NULL,
    expires_at timestamptz NOT NULL,
    used boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS device_leases (
    lease_id text PRIMARY KEY,
    work_id text NOT NULL,
    device_id text NOT NULL REFERENCES devices(device_id),
    status text NOT NULL DEFAULT 'ACTIVE',
    leased_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    completed_at timestamptz,
    ambiguous_side_effect boolean NOT NULL DEFAULT false,
    revision integer NOT NULL DEFAULT 1
);

-- At most one ACTIVE lease per Work — enforced at the DB level, not just in
-- application code, so two devices can never both believe they hold the lease.
CREATE UNIQUE INDEX IF NOT EXISTS device_leases_active_work_idx
    ON device_leases (work_id) WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS device_leases_device_idx ON device_leases (device_id);

COMMIT;
