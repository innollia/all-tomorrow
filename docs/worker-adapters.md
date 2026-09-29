# Worker Adapters

This document describes the worker adapter subsystem for executing external AI coding agent CLIs as part of the All Tomorrow control plane.

> [!NOTE]
> These worker adapters (`AntigravityWorker`, `OpenCodeWorker`, `CodexWorker`, and `KiroWorker`) are CLI process adapters executing local binaries. They are **not** the existing Antigravity Manager bridge adapter listed in the roadmap.

## Local worker connection — 2026-09-27

- 상태: **개발완료** (로컬 연결 및 실제 산출물 검증)
- 범위: 사용자 요청으로 이 PC의 네 CLI를 기존 `WorkerService`에 연결한다. Stage 0 gate의 한정 예외이며 Stage 1 전체 착수나 04B/04C 완료를 뜻하지 않는다.
- 실행 진입점: `python -m all_tomorrow.local_workers` 또는 설치 후 `all-tomorrow-worker`.
- 호스트 설정: `config/workers.local.json` (Git 제외). `config/workers.example.json`은 공유 템플릿이다.
- `allowed_roots`와 요청 `--cwd`를 모두 명시한다. 현재 로컬 설정은 이 저장소만 허용한다.

```powershell
# 저장소 루트, 기존 .venv 사용
.venv/Scripts/python.exe -m all_tomorrow.local_workers list
.venv/Scripts/python.exe -m all_tomorrow.local_workers run codex --cwd C:/projects/all-tomorrow --task "README를 읽고 구조를 설명해줘"
# worker 자리에 opencode / kiro / antigravity도 지정 가능
# 긴 요청은 --task 대신 --task-file <UTF-8 파일> 사용
.venv/Scripts/python.exe scripts/smoke_local_workers.py --workers codex opencode kiro antigravity
```

`list`는 실행 파일과 버전을 확인한다. 로그인·모델 가용성을 보증하지 않으며 `authentication: not_checked`를 반환한다. 실행 결과의 `SUCCESS`는 CLI protocol 완료이고, 요청한 기능의 성공은 실제 산출물로 추가 판정한다. smoke 명령은 매번 새 작업 폴더와 무작위 확인 문자열을 만들고 파일 내용까지 검증한다. 결과는 `.artifacts/local-workers/<실행 ID>/results.json`에 남긴다.

## Device agent (Tailscale) — 2026-09-29

- 상태: **개발완료**. 계획서: `docs/plans/device-agent-tailscale.md`. 다른 PC/기기를 tailnet으로 붙여 중앙 서버(`http://100.97.113.3:8080`)의 일을 pull 방식으로 처리한다.
- 등록 코드는 admin 로그인 후 `/devices` 화면에서 1회용으로 발급한다. 발급 후 아래 명령을 새 기기에서 실행한다 (PowerShell, 절대경로, 관리자 권한 불필요).

```powershell
git clone https://github.com/innollia/all-tomorrow.git C:\all-tomorrow
cd C:\all-tomorrow
python -m venv .venv
C:\all-tomorrow\.venv\Scripts\python.exe -m pip install -e .
powershell -NoProfile -ExecutionPolicy Bypass -File C:\all-tomorrow\scripts\install_device_agent.ps1 -ServerUrl "http://100.97.113.3:8080" -RegistrationCode "<발급받은 코드>" -RepoPath "C:\all-tomorrow"
Start-ScheduledTask -TaskName "AllTomorrowDeviceAgent"
```

- 등록 후 토큰은 `%LOCALAPPDATA%\all-tomorrow\device_agent_state.json`에 저장되며 재부팅/재로그인 시 작업 스케줄러가 자동 재시작한다. 90초간 하트비트가 없으면 웹 화면에서 OFFLINE으로 표시된다. lease 만료로 대기 상태가 된 Work는 부수효과가 있었을 수 있으면 `ambiguous_side_effect`로 표시되고 자동 재실행되지 않는다.
- 기기를 더 이상 쓰지 않으면 `/devices` 화면의 "기기 끊기"로 토큰을 폐기한다.


CLI 탐색은 PATH를 우선 사용하고 Windows의 Codex/agy/Kiro 설치 위치와 OpenCode npm 캐시를 확인한다. OpenCode Desktop GUI 실행 파일을 CLI로 취급하거나 `npx -y`로 매 실행 새 버전을 내려받지 않는다. 캐시가 지워지면 명시적으로 unavailable이 된다. 고정 경로가 필요하면 worker 항목에 `argv` 배열을 지정한다(OpenCode는 끝에 `run` 포함).

### 실행과 권한

- 네 worker 모두 기존 대화를 resume하지 않고 새 실행을 만든다. Codex는 `--ephemeral`을 사용한다.
- Codex는 `workspace-write`, 비대화형 approval 정책, Windows `unelevated` sandbox를 명시한다. 로컬 템플릿의 `ignore_user_config: true`는 사용자 config의 추가 MCP/hooks를 불러오지 않으며 로그인은 호스트 것을 사용한다. 모델이 필요하면 `options.model`로 지정한다.
- Kiro는 설치된 CLI의 `chat --no-interactive --output-format text`를 사용한다. 기본 신뢰 도구는 `fs_read,fs_write`; 필요한 도구 목록은 `options.trusted_tools`로 정한다. 아직 검증하지 않은 JSON stream schema를 추측하지 않는다.
- 호스트 로그인 파일은 각 CLI가 관리한다. 환경은 OS·사용자 경로·proxy/certificate allowlist만 상속한다. 추가 인증 환경변수는 worker별 `env_names`에 **이름만** 적고 실제 값은 호스트 환경에 둔다.
- cwd 검사는 초기 작업 위치를 제한한다. Codex 외 CLI에 공통 OS sandbox가 생기는 것은 아니며 각 도구의 권한 설정이 계속 적용된다.
- timeout/output cap/cancellation 시 이 실행의 로컬 프로세스 트리를 종료한다. 이미 발생한 파일 변경이나 원격 작업까지 롤백한다는 뜻은 아니다.
- 자동 worker 선택이나 Web/Discord 요청 전송은 이번 실행 진입점에 추가하지 않았다. 기존 `WorkerRunNode`에서도 이 service를 주입하면 같은 adapter를 사용할 수 있다.

### Eve / Discord Antigravity 검토

로컬 코드의 실제 진입점은 `C:/projects/eve-scene-runtime/src/discord/manager-bridge.mjs`다. `ManagerSession`이 기존 conversation ID와 정산·페르소나·롤오버 상태를 관리하며 `agentapi new-conversation/send-message`를 호출한다. Windows 기본 runner는 Antigravity의 `language_server.exe`; Linux 기본 runner는 `agy-agentapi-compat.mjs`이며 그 wrapper가 `agy` print 호출로 변환한다.

상세 문서의 `manager-session-persistence.mjs`는 로컬에 없었다. 이 조사에서 로컬 `.env`의 관련 경로 override와 해당 Discord 봇 프로세스는 발견하지 못했다. 따라서 현재 운영 Discord의 원격 배치·연결 상태까지 검증한 것은 아니다.

All Tomorrow는 설치된 `agy` CLI를 직접 호출한다. Eve의 ManagerSession, Discord 메시지, 정산/기억/페르소나 파일을 공유하거나 수정하지 않는다. 별도 Discord 봇을 만들 필요도 없다.

### 검증 기록

2026-09-27 이 PC에서 기존 WorkerService를 통해 네 도구 모두 실제 `proof.txt` 생성, 정확한 내용, 정상 CLI 결과 회수를 확인했다. 아래 증거는 CLI 직접 호출만 한 초기 probe와 구분한다.

| Worker | 확인한 CLI 버전 | 결과 | 로컬 증거 (`.artifacts/local-workers/` 기준) |
|---|---|---|---|
| Codex | 0.158.0-alpha.2.1 | SUCCESS + 파일 내용 일치 | `result-codex.json`, `run-codex/proof.txt` |
| OpenCode | 1.18.32 | SUCCESS + 파일 내용 일치 | `result-opencode.json`, `run-opencode/proof.txt` |
| Antigravity | 1.2.12 | SUCCESS + 파일 내용 일치 | `20260927T122558Z-d535284f/results.json` |
| Kiro | 2.24.1 | SUCCESS + 파일 내용 일치 | `20260927T122718Z-b35d98c3/results.json` |

파일 SHA-256과 request/trace 연결은 `verified-summary.json` 및 각 result에 남겼다. `.artifacts`는 Git에 포함하지 않으므로 다른 PC에서는 smoke 명령으로 다시 확인한다.

- Kiro 최초 호출은 미로그인으로 실패했고, 사용자 로그인 후 실제 실행을 통과했다.
- Antigravity 최초 통합 호출은 `SUCCESS` envelope의 response가 비어 `INVALID_OUTPUT`으로 처리했다(`result-antigravity.json`). 후속 독립 실행의 성공은 확인했으나 최초 빈 응답의 원인은 미확정이다. 자동 재시도로 성공 처리하지 않는다.
- Codex 최초 Windows 호출은 쓰기를 거부했다. `windows.sandbox="unelevated"`를 명시한 workspace-write 실행에서 파일 생성을 확인했다.
- 관련 회귀 검증: `tests/test_local_workers.py`, `tests/test_workers.py`, `tests/test_worker_pipeline.py`, `tests/test_registry.py` 73개 통과. 추가 CLI UTF-8 출력 회귀 1개도 별도 통과해 총 74개를 확인했다.
- 테스트 범위: 네 adapter의 실제 자식 프로세스 → WorkerRunNode → 파일 산출물, 불완전/실패 출력, 인증 실패, 환경 격리·오류 마스킹, 출력 초과, timeout 시 자식 프로세스 정리, cwd 거부. 외부 네 CLI live 실행은 위 증거로 별도 확인했다.

이 결과는 로컬 실행 연결의 완료이며 장기 작업 복구, 실제 AWS/laptop 배치, Web/Discord ingress, Stage 1 전체 완료를 보증하지 않는다.

## Overview

Worker adapters implement the `WorkerAdapter` protocol to invoke external processes safely:

- **Fail closed**: Any error condition results in a structured `WorkerResult` with `WorkerStatus` indicating the failure mode.
- **No shell execution**: Uses `asyncio.create_subprocess_exec` with explicit `argv` only, never `shell=True`.
- **Explicit working directory**: `cwd` must be provided in request payload and validated against configured allowed roots (`_resolve_cwd`).
- **Secret & path sanitization**: Inherited environment is allowlisted; secret values (`KEY`, `TOKEN`, `SECRET`, `PASSWORD`) in failures and filesystem home paths (`HOME`, `USERPROFILE`) are redacted from error messages. Empty home variables never corrupt error strings.
- **Stderr secrecy**: Subprocess stderr output is sanitized to prevent credential leakage.
- **Combined output limits**: Stdout and stderr are read concurrently against a shared byte limit; excess output terminates the process before buffering the full stream.
- **Timeout enforcement & reaping**: Processes that exceed timeout are terminated with their local descendants and reaped.
- **Availability gating**: Workers check executable availability via `shutil.which` and `PATHEXT` before registration, and map missing executables to `WorkerStatus.EXECUTABLE_NOT_FOUND`.

## Contract Types

### WorkerRequest

```python
@dataclass(frozen=True, slots=True)
class WorkerRequest:
    request_id: str               # Unique request identifier
    trace_id: str                 # Distributed trace identifier
    project_id: str | None        # Optional project context
    capabilities: frozenset[str]  # Required capabilities for this request
    payload: dict[str, Any]       # Input data; must include "cwd"
```

### WorkerResult

```python
@dataclass(frozen=True, slots=True)
class WorkerResult:
    request_id: str
    trace_id: str
    status: WorkerStatus
    payload: dict[str, Any] | None = None
    duration_ms: int = 0
    error: str | None = None
```

### WorkerStatus

```python
class WorkerStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    EXECUTABLE_NOT_FOUND = "EXECUTABLE_NOT_FOUND"
    TRAVERSAL_BLOCKED = "TRAVERSAL_BLOCKED"
    EMPTY_OUTPUT = "EMPTY_OUTPUT"
    OUTPUT_TOO_LARGE = "OUTPUT_TOO_LARGE"
```

---

## AntigravityWorker

Executes the Google Antigravity CLI (`agy.exe` on Windows, `agy` on Unix) via subprocess.

### Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `argv` | `list[str] \| None` | `["agy.exe"]` (Windows) / `["agy"]` (Unix) | Base executable command |
| `allowed_roots` | `tuple[str, ...]` | Required | Filesystem roots that `cwd` may resolve within |
| `mode` | `str` | `"accept-edits"` | Agent execution mode (`accept-edits`, `plan`) |
| `dangerously_skip_permissions` | `bool` | `False` | Auto-approve tool permission requests (`--dangerously-skip-permissions`) |
| `effort` | `str` | `"high"` | Reasoning effort (`low`, `medium`, `high`) |
| `model` | `str \| None` | `None` | Optional model override passed via `--model` |
| `output_format` | `str` | `"json"` | Output format passed via `--output-format` (`json`, `text`) |
| `timeout_seconds` | `float` | `120.0` | Process timeout in seconds |
| `output_limit_bytes` | `int` | `1_048_576` | Max combined stdout + stderr bytes (1 MiB) |
| `env` | `dict[str, str] \| None` | `None` | Additional environment variables |

### Invocation and Prompt Protocol

Antigravity operates in non-interactive print mode with a detailed plain-text prompt:

```python
argv = [
    *base_argv,
    "--mode", mode,                              # default: "accept-edits"
    # "--dangerously-skip-permissions",          # if dangerously_skip_permissions=True
    "--effort", effort,                          # default: "high"
    # "--model", model,                          # only if explicitly set
    "--output-format", output_format,            # default: "json"
    "--print", prompt,                           # plain-text task prompt
]
```

The prompt preserves `request_id`, `trace_id`, `project_id`, `capabilities`, `task`/`instructions`, `constraints`, `acceptance_criteria`, and `expected_result_format`. Stdin is set to `DEVNULL`.

### Output Handling

When `--output-format json` is used, the CLI returns a JSON envelope:

```json
{
  "conversation_id": "...",
  "status": "SUCCESS",
  "response": "...",
  "duration_seconds": 2.5,
  "usage": { ... }
}
```

The worker parses this envelope directly into `result.payload`. If textual output mode is used or the output is text, it returns `payload={"output": stdout_str, "text": stdout_str}`.

### Capabilities

`frozenset({"coding", "repo_edit", "analysis"})`

---

## OpenCodeWorker

Executes the installed OpenCode CLI (`opencode run`; the local composition resolves its executable path) via subprocess.

### Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `argv_prefix` | `list[str] \| None` | `["opencode", "run"]` | Base command prefix |
| `allowed_roots` | `tuple[str, ...]` | Required | Filesystem roots that `cwd` may resolve within |
| `model` | `str \| None` | `None` | Model override (`provider/model`). Defaults to OpenCode configured default |
| `agent` | `str \| None` | `None` | Agent override. Defaults to OpenCode configured default |
| `format` | `str` | `"json"` | Event format (`json`, `default`) |
| `auto` | `bool` | `False` | Auto-approve permissions (`--auto`) |
| `timeout_seconds` | `float` | `180.0` | Process timeout |
| `output_limit_bytes` | `int` | `1_048_576` | Max combined stdout + stderr bytes |
| `env` | `dict[str, str] \| None` | `None` | Additional environment variables |

### Invocation

The worker constructs argv as:

```python
argv = [
    *argv_prefix,
    "--format", format,
    # "--model", model,    # only if explicitly specified
    # "--agent", agent,    # only if explicitly specified
    # "--auto",             # only if auto=True
    prompt,                 # positional message argument
]
```

Stdin is set to `DEVNULL`.

### Capabilities

`frozenset({"coding", "repo_edit", "analysis", "terminal"})`

---

## Registry Helper and WorkerService

```python
async def register_available_workers(
    registry: CapabilityRegistry | WorkerService,
    *,
    antigravity_argv: list[str] | None = None,
    opencode_argv_prefix: list[str] | None = None,
    codex_argv: list[str] | None = None,
    kiro_argv: list[str] | None = None,
    allowed_roots: tuple[str, ...],
    **worker_kwargs: Any,
) -> list[str]:
```

Checks executable availability via `shutil.which` and registers available workers. When given a `WorkerService`, it atomically binds both metadata in `CapabilityRegistry` and the executable adapter in `WorkerService`. Returns list of registered worker IDs.

### WorkerService

`WorkerService` binds `CapabilityRegistry` metadata with executable `WorkerAdapter` instances:
- Enforces consistency at registration (`worker.worker_id == adapter.worker_id` and `worker.capabilities == adapter.capabilities`).
- Rejects duplicate registrations.
- Exposes `select_worker(request)` for metadata selection and `execute(worker_id, request)` for adapter execution.
- Provides typed public `list_workers()` and `get_worker(worker_id)` access.

### Pipeline Node Integration

- **`capability.select`**: Selects best matching available worker based on `required_capabilities` and `privacy_tags`. If no worker satisfies requirements, fails closed with actionable error (unless `allow_policy_relaxation: True` explicitly permits user override). User overrides strictly enforce capability and privacy constraints.
- **`worker.run`** (or **`agent.run`**): Consumes selected `worker_id`, propagates original user message, explicit task, constraints, acceptance criteria, expected result format, and `cwd`.
  - Never guesses `cwd`; if missing and mutation is possible, returns `NEED_USER` with `required_fields=("cwd",)` targeting the exact blocked step ID.
  - Maps `WorkerStatus` deterministically: `SUCCESS -> NodeStatus.SUCCESS`, `TIMEOUT -> NodeStatus.RETRY`, and failure modes (`INVALID_OUTPUT`, `EMPTY_OUTPUT`, `OUTPUT_TOO_LARGE`, `TRAVERSAL_BLOCKED`, `EXECUTABLE_NOT_FOUND`, `FAILED`) to `NodeStatus.FAILED` (unless `retry_on_fail: True` is configured).
  - Emits minimal provenance events (`worker.executed`) recording trace ID, request ID, project ID, status, and duration, without leaking prompts, constraints, or secrets.

---

## Security Considerations

1. **No `shell=True`**: All workers invoke `asyncio.create_subprocess_exec` directly.
2. **Path traversal prevention**: Working directory is strictly validated against `allowed_roots` using resolved paths.
3. **Error & stderr sanitization**: Errors and stderr output pass through `_sanitize_error()`, which redacts `HOME`, `USERPROFILE`, and sensitive environment variables (`KEY`, `TOKEN`, `SECRET`, `PASSWORD`). Unset home variables never corrupt error messages.
4. **Combined output limit**: Limits account for `len(stdout) + len(stderr)` preventing memory leaks.
5. **Process termination & reaping**: On timeout, processes are killed (`kill()`) and waited on (`wait()`) to avoid orphaned processes.
6. **Executable not found**: Missing binaries return `WorkerStatus.EXECUTABLE_NOT_FOUND` with sanitized descriptions.
7. **Event provenance secrecy**: Pipeline events record provenance linkage (run/step/trace/project/worker ID) while strictly omitting raw prompts, constraints, payloads, and secrets. Invalid event actor or type fails closed predictably.