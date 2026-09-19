# 04B — Codex Worker

## Status

- 상태: **시작안했음**
- 지금 시작 가능: **예**
- 선행조건: 없음

## 목적

현재 `AntigravityWorker` / `OpenCodeWorker`와 같은 WorkerAdapter 경계에 Codex CLI의 non-interactive execution을 추가한다.

## 수정 파일

- 수정: `src/all_tomorrow/adapters/workers.py`
- 수정: `src/all_tomorrow/adapters/__init__.py`
- 수정: `tests/test_workers.py`
- 수정: `tests/test_worker_pipeline.py`
- 필요 시 수정: `docs/worker-adapters.md`

새 worker framework를 만들지 않는다. 현재 subprocess helper를 재사용한다.

## CodexWorker

class:

`CodexWorker`

constructor pattern은 OpenCodeWorker와 맞춘다.

필드:

- `argv_prefix` default: OS에 맞는 `codex exec`
- `allowed_roots`
- `model: str | None`
- `sandbox: str = "workspace-write"`
- `ephemeral: bool = True`
- `json_output: bool = True`
- `timeout_seconds`
- `output_limit_bytes`
- `env`

worker_id:

- `codex`

capabilities:

- coding
- repo_edit
- analysis
- terminal

## argv

초기 자동화는 current official non-interactive path인 `codex exec` 사용.

기본 권한:

- `--sandbox workspace-write`
- `--ephemeral`
- JSON event output 사용

`danger-full-access`를 기본값이나 fallback으로 넣지 않는다.

prompt는 기존 `_build_worker_prompt(request)` 재사용.

cwd 검증은 기존 `_resolve_cwd()` 재사용.

process timeout/output limit/error redaction은 `_run_process_safe()` 재사용.

## Output parsing

Codex JSON output은 newline JSON event stream을 허용.

parser 결과 최소 형태:

- events: parsed JSON event list
- final/output: 가능한 경우 최종 agent message
- raw stdout 전체를 Event metadata에 넣지 않음

JSON 형식이 달라져도 worker가 provider-specific detail을 `WorkerResult.payload` 안에서 정규화하고 PipelineRuntime이 Codex event schema를 직접 알지 않게 한다.

## Authentication

CLI가 이미 가진 login/auth를 재사용할 수 있다.

API key 방식이 필요할 때도 key를 Work payload로 전달하지 않는다.

repo가 실행하는 untrusted code가 process-wide credential을 읽을 수 있는 구조를 기본값으로 만들지 않는다.

## register_available_workers

signature에:

- `codex_argv_prefix: list[str] | None = None`

추가.

executable available일 때 기존 WorkerService registration pattern 그대로 등록.

## 테스트

`tests/test_workers.py`에 OpenCode 테스트와 동형:

- successful JSONL parse
- argv includes `exec`
- workspace-write sandbox
- ephemeral
- timeout
- nonzero exit
- missing executable
- traversal blocked
- output too large
- invalid JSON
- secret sanitization

`tests/test_worker_pipeline.py`:

- register_available_workers가 Codex 등록
- capability.select가 Codex를 후보로 볼 수 있음
- pipeline core에 `if codex` 추가 없이 실행

## 하지 말 것

- Codex 전용 pipeline
- Codex raw event type을 core enum으로 모두 복제
- danger-full-access default
- credential을 WorkerRequest.payload에 넣기
- Antigravity/OpenCode를 Codex에 맞춰 불필요하게 재작성

## 완료조건

1. Codex CLI available 시 worker registry 등록
2. 기존 WorkerRunNode로 실행 가능
3. workspace root 밖 traversal 차단
4. current worker regression 전부 통과
