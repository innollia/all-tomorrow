# Worker Adapters

This document describes the worker adapter subsystem for executing external AI coding agent CLIs as part of the All Tomorrow control plane.

> [!NOTE]
> These worker adapters (`AntigravityWorker` and `OpenCodeWorker`) are CLI process adapters executing local binaries. They are **not** the existing Antigravity Manager bridge adapter listed in the roadmap.

## Overview

Worker adapters implement the `WorkerAdapter` protocol to invoke external processes safely:

- **Fail closed**: Any error condition results in a structured `WorkerResult` with `WorkerStatus` indicating the failure mode.
- **No shell execution**: Uses `asyncio.create_subprocess_exec` with explicit `argv` only, never `shell=True`.
- **Explicit working directory**: `cwd` must be provided in request payload and validated against configured allowed roots (`_resolve_cwd`).
- **Secret & path sanitization**: Environment secrets (`KEY`, `TOKEN`, `SECRET`, `PASSWORD`) and filesystem home paths (`HOME`, `USERPROFILE`) are redacted from error messages. Empty home variables never corrupt error strings.
- **Stderr secrecy**: Subprocess stderr output is sanitized to prevent credential leakage.
- **Combined output limits**: Configurable byte limit accounts for `len(stdout) + len(stderr)` to prevent memory exhaustion.
- **Timeout enforcement & reaping**: Processes that exceed timeout are killed (`proc.kill()`) and reaped (`await proc.wait()`).
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

Executes OpenCode CLI (`npx.cmd -y opencode-ai run` on Windows, `npx -y opencode-ai run` on Unix) via subprocess.

### Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `argv_prefix` | `list[str] \| None` | Platform default (`npx.cmd`/`npx -y opencode-ai run`) | Base command prefix |
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

## Registry Helper

```python
async def register_available_workers(
    registry: CapabilityRegistry,
    *,
    antigravity_argv: list[str] | None = None,
    opencode_argv_prefix: list[str] | None = None,
    allowed_roots: tuple[str, ...],
    **worker_kwargs: Any,
) -> list[str]:
```

Checks executable availability via `shutil.which` and only registers workers whose executables are present on PATH. Returns list of registered worker IDs.

### Example

```python
from all_tomorrow.adapters import register_available_workers
from all_tomorrow.registry import CapabilityRegistry

registry = CapabilityRegistry()
registered = await register_available_workers(
    registry,
    antigravity_argv=["agy.exe"],
    opencode_argv_prefix=["npx.cmd", "-y", "opencode-ai", "run"],
    allowed_roots=("/workspace", "/projects"),
    timeout_seconds=60.0,
)
# registered contains worker IDs that are actually available
```

---

## Security Considerations

1. **No `shell=True`**: Both workers invoke `asyncio.create_subprocess_exec` directly.
2. **Path traversal prevention**: Working directory is strictly validated against `allowed_roots` using resolved paths.
3. **Error & stderr sanitization**: Errors and stderr output pass through `_sanitize_error()`, which redacts `HOME`, `USERPROFILE`, and sensitive environment variables (`KEY`, `TOKEN`, `SECRET`, `PASSWORD`). Unset home variables never corrupt error messages.
4. **Combined output limit**: Limits account for `len(stdout) + len(stderr)` preventing memory leaks.
5. **Process termination & reaping**: On timeout, processes are killed (`kill()`) and waited on (`wait()`) to avoid orphaned processes.
6. **Executable not found**: Missing binaries return `WorkerStatus.EXECUTABLE_NOT_FOUND` with sanitized descriptions.