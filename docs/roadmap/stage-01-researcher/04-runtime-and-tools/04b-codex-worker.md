# 04B — Codex Worker

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 완료

## 목적

기존 WorkerAdapter 경계에 Codex CLI non-interactive execution을 추가한다. 새 worker framework를 만들지 않는다.

## Contract

- worker_id: codex
- capabilities: coding / repo_edit / analysis / terminal
- executable/version discovery
- workspace cwd는 04C에서 resolution된 명시적 path만 사용
- sandbox 기본 workspace-write
- ephemeral execution
- JSON/JSONL event output normalization
- timeout/output cap
- environment allowlist/redaction

danger-full-access를 default/fallback으로 사용하지 않는다.

## Parser boundary

Codex raw event schema는 WorkerResult 내부 normalized fields로 제한한다.

- final/output
- event refs/summary
- exit/error category
- usage if available
- artifact refs

raw stdout 전체를 Event metadata에 저장하지 않는다.
unknown event type은 core enum을 늘리는 대신 adapter가 보존 가능한 opaque evidence ref 또는 ignored metadata로 처리한다.

## Authentication

- CLI login/key는 host credential domain
- Work payload에 credential 전달 금지
- untrusted repository process가 process-wide secret를 읽지 못하도록 environment allowlist
- command log/redaction canary test

## Requirements

- successful JSONL parse
- version discovery/unsupported version explicit failure
- workspace-write + ephemeral argv
- timeout/nonzero/missing executable
- invalid JSON/oversize output
- traversal/symlink escape blocked
- secret sanitization
- registry capability selection without core name branch
- existing worker regression

## 완료조건

Stage 0 이후 current supported Codex CLI에서 실제 non-interactive run을 수행하고 기존 WorkerRunNode/registry contract 안에서 동작해야 한다.
