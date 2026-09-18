# Worker Adapters

This document describes the worker adapter subsystem for executing external AI coding agents as part of the All Tomorrow control plane.

## Overview

Worker adapters provide a standardized `WorkerAdapter` protocol for executing external processes (CLI tools) safely. The design principles are:

- **Fail closed**: Any error condition results in a structured `WorkerResult` with `WorkerStatus` indicating the failure mode
- **No shell execution**: Uses `asyncio.create_subprocess_exec` with explicit `argv` only, never `shell=True`
- **Explicit working directory**: `cwd` must be provided in request payload and validated against configured allowed roots
- **No credential leakage**: Environment variables, full command lines, and raw stderr are never exposed in public errors
- **Output limits**: Configurable output size caps prevent memory exhaustion
- **Timeout enforcement**: Configurable per-worker timeouts with process termination on expiry
- **Availability gating**: Workers are only registered/advertised when their executable is actually available

## Contract Types

### WorkerRequest

```python
@dataclass(frozen=True, slots=True)
class WorkerRequest:
    request_id: str          # Unique request identifier
    trace_id: str            # Distributed trace identifier
    project_id: str | None   # Optional project context
    capabilities: frozenset[str]  # Required capabilities for this request
    payload: dict[str, Any]  # Arbitrary input data; must include "cwd"
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

## AntigravityWorker

Executes the Antigravity CLI via subprocess.

### Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `argv` | `list[str]` | Required | Base command (e.g., `["antigravity"]`) |
| `allowed_roots` | `tuple[str, ...]` | Required | Filesystem roots that `cwd` may resolve within |
| `model` | `str` | `"opus"` | Model identifier passed via `--model` |
| `effort` | `str` | `"high"` | Effort mode passed via `--effort` |
| `timeout_seconds` | `float` | `120.0` | Process timeout |
| `output_limit_bytes` | `int` | `1_048_576` | Max stdout bytes (1 MiB) |
| `env` | `dict[str, str] | None` | `None` | Additional environment variables |

### Invocation

The worker constructs argv as:

```python
argv = [
    *base_argv,
    "--model", model,
    "--effort", effort,
    "--json",
]
```

Input is passed via stdin as JSON. Expected stdout is a JSON object.

### Capabilities

`frozenset({"coding", "repo_edit", "analysis"})`

## OpenCodeWorker

Executes the OpenCode CLI (`npx opencode-ai run`) via subprocess.

### Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `argv_prefix` | `list[str] | None` | Platform default | Base command prefix. Windows: `["npx.cmd", "-y", "opencode-ai", "run"]`, Unix: `["npx", "-y", "opencode-ai", "run"]` |
| `allowed_roots` | `tuple[str, ...]` | Required | Filesystem roots that `cwd` may resolve within |
| `model` | `str` | `"default"` | Model identifier passed via `--model` |
| `agent` | `str` | `"default"` | Agent identifier passed via `--agent` |
| `timeout_seconds` | `float` | `180.0` | Process timeout |
| `output_limit_bytes` | `int` | `1_048_576` | Max stdout bytes (1 MiB) |
| `env` | `dict[str, str] | None` | `None` | Additional environment variables |

### Invocation

The worker constructs argv as:

```python
argv = [
    *argv_prefix,
    "--model", model,
    "--agent", agent,
]
```

**Important**: `--auto` is NOT enabled by default. Credentials are NOT read from environment or config files.

Input is passed via stdin as JSON. Expected stdout is a JSON object.

### Capabilities

`frozenset({"coding", "repo_edit", "analysis", "terminal"})`

## Registry Helper

```python
def register_available_workers(
    registry: CapabilityRegistry,
    *,
    antigravity_argv: list[str] | None = None,
    opencode_argv_prefix: list[str] | None = None,
    allowed_roots: tuple[str, ...],
    **worker_kwargs: Any,
) -> list[str]:
```

Checks executable availability via `shutil.which` (or absolute path check) and only registers workers whose executables are found. Returns list of registered worker IDs.

### Example

```python
from all_tomorrow.adapters import register_available_workers
from all_tomorrow.registry import CapabilityRegistry

registry = CapabilityRegistry()
registered = register_available_workers(
    registry,
    antigravity_argv=["antigravity"],
    opencode_argv_prefix=["npx", "-y", "opencode-ai", "run"],
    allowed_roots=("/workspace", "/projects"),
    timeout_seconds=60.0,
)
# registered contains only workers with available executables
```

## Security Considerations

1. **No shell=True**: Both workers use `asyncio.create_subprocess_exec` with explicit argv arrays
2. **Path traversal prevention**: `cwd` is resolved and checked against `allowed_roots` using `Path.relative_to()`
3. **Error sanitization**: All error messages passed through `_sanitize_error()` which redacts:
   - Home directory paths (`HOME`, `USERPROFILE`)
   - Environment variables containing KEY, TOKEN, SECRET, PASSWORD
4. **No credential exposure**: Workers do not read `.env` files, credential helpers, or config files
5. **Output limits**: Prevents memory exhaustion from runaway processes
6. **Process isolation**: stdin/stdout/stderr pipes only; no terminal allocation

## Testing

Tests use `FakeProcess` to simulate subprocess behavior without calling real executables or network. See `tests/test_workers.py` for comprehensive coverage including:

- Successful execution with JSON output
- Timeout handling with process kill
- Non-zero exit codes
- Empty output detection
- Output size limit enforcement
- Invalid JSON output handling
- Path traversal blocking
- Missing `cwd` validation
- Executable availability checks
- Default argv prefix on Windows vs Unix
- Registry helper availability gating
- Error message sanitization

Run tests with:

```bash
pytest tests/test_workers.py -v
```