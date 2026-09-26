# Idea — Reuse KiroCrew's proven tech to strengthen all-tomorrow

Source: user steering (2026-09-27). all-tomorrow is building capabilities that
KiroCrew (the agent layer this project runs under) already ships in production.
Rather than re-derive each from scratch, adopt or mirror KiroCrew's battle-tested
mechanisms where they map cleanly onto an all-tomorrow packet.

## Direct overlaps worth harvesting

| all-tomorrow packet | KiroCrew mechanism to reuse / learn from |
|---|---|
| 01C durable bridge / 04D runtime | KiroCrew's DBOS-backed durable execution + pod (systemd-unit) preview gateway pattern |
| 02 researcher loop | KiroCrew `monitor_start`/`monitor_watch` self-session prompt loop (deadline-preserving, gate-on-change) — exactly the "wake on new observation, no model turn if nothing changed" semantics 02A/02B want |
| 3.2A/3.2B triggers + watchers | KiroCrew `cron_add` script/command mode (zero-LLM polling), `minimal_context`, `persistent_session=false` — the cheap-poll design 3.2B needs |
| 3.2C lessons | KiroCrew `learn_add`/`learn_list` durable-correction store with `applies` tiers + `repo_scope` |
| 05A/05B report | KiroCrew `send_notification` (bell feed, priority/group) + digest-cron pattern |
| 04B/04C workers/workspace | KiroCrew subagent orchestration (`spawn_run`, scoped context flags) + worktree pods |
| memory / provenance | KiroCrew memory V2 (per-member private store) as a model for scoped Goal/Work provenance recall |
| 04F artifacts | KiroCrew artifact registry (versioned, folders, revert) |

## Recommended approach

1. Where KiroCrew EXPOSES the mechanism as a callable tool (cron, monitor,
   notify, learn), all-tomorrow running *inside* KiroCrew can call it directly
   instead of re-implementing — treat KiroCrew as the substrate, like DBOS.
2. Where it is a design pattern (deadline-preserving loop, gate-on-change,
   zero-LLM poll, scoped context), copy the pattern into the matching packet.
3. Keep the domain contracts (Goal/Work/Run, ExecutionRef ownership, fail-closed
   budgets) — those are all-tomorrow's own semantics and must not be replaced by
   a substrate's internal types (same rule as D-LOCK: no backend type leaks into
   the domain).

## Status

Idea captured for the roadmap. Concrete adoption would be a Stage-0-style ADR
("substrate = KiroCrew tools for cron/monitor/notify/learn") plus per-packet
follow-ups; not yet scheduled. The current build implements the packets
substrate-independently so either path (call KiroCrew, or run standalone) stays open.
