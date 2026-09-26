BEGIN;

CREATE TABLE IF NOT EXISTS public.at_run_executions (
    run_id text PRIMARY KEY,
    execution_id text NOT NULL,
    workflow_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.at_signals_seen (
    execution_id text NOT NULL,
    signal_id text NOT NULL,
    delivered_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (execution_id, signal_id)
);

COMMIT;
