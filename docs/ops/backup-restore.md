# Stage 2.2C — Backup / Restore

Extends the 04D single-node deploy with concrete backup/restore targets. RPO/RTO
are decided here (deployment ADR value) and the three state owners are backed up
independently — they are NOT a single transaction-consistent snapshot.

## Objectives

- **RPO** (max data loss): 1 hour — hourly `pg_dump` of both databases to S3 (SSE).
- **RTO** (max recovery time): 1 hour — restore into a fresh node from the latest
  hourly dump + apply migrations + run cross-store reconciliation.

## Backup owners (separate)

| State | Owner | Mechanism | Schedule | Retention |
|---|---|---|---|---|
| application DB (`all_tomorrow`) | app | `pg_dump` → S3 (SSE, versioned) | hourly | 7d rolling + 30d daily |
| durable system DB (`all_tomorrow_dbos`) | DBOS | `pg_dump` (SDK-safe) → S3 | hourly | 7d active-preserving |
| artifact metadata (ArtifactRefs) | artifact store | included in the app DB dump; object bytes are content-addressed in S3 | hourly | matches artifact retention class |

Backup artifacts live in a private S3 bucket, SSE-encrypted, access scoped to the
instance role (S2-22C-01).

## Isolated restore (S2-22C-02)

1. Provision a SEPARATE target (never restore over the live node).
2. `pg_restore` both databases from the chosen point.
3. Apply the migration chain (idempotent `CREATE TABLE IF NOT EXISTS`).
4. Run `DurableRunBridge.reconcile_starting_runs()` — STARTING Runs with no
   ExecutionRef converge to one logical external execution, recovering semantic
   Run identity (application DB and durable state are reconciled, not assumed
   consistent).

## RPO/RTO measurement (S2-22C-03)

Recorded from an actual isolated restore drill on the live stack: timestamp of the
last backup vs the incident (RPO), and start-of-restore vs first green healthcheck
(RTO). Values are logged in the deployment ADR after the drill.

## Restored secret/session rotation (S2-22C-04)

After a restore, all sessions are invalidated (session store is not restored) and
provider/gateway secrets are rotated per docs/ops/secrets-and-alerts.md — a
restored backup must never resurrect a live credential or an authenticated
session.
