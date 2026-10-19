# Claude → All Tomorrow MCP 연결

- 상태: **개발중** — `feat/port-console-features`로 이식 중. 이식본은 단위 테스트 5개와 stdio·WMI 분리 실행 확인을 통과했다(아래). Claude 세션에서 이식본을 호출한 확인은 아직 없다(등록이 아직 이전 checkout을 가리킨다).
- 범위: 2026-10-19 사용자 요청. Claude 세션이 All Tomorrow에 붙어 등록된 프로젝트를 보고 이 PC의 로컬 worker에 작업을 맡긴다. 이 PC 로컬(stdio) 전용이며 중앙 서버를 거친 원격 실행, durable queue, 자동 worker 선택은 포함하지 않는다.

## 이식 기록

처음 구현은 stale 브랜치 `feat/stage-00d-close`에서 했다. 이 브랜치는 main의 83개 커밋(Stage 1–3, device agent 포함) 이전에 갈라졌다. 2026-10-19 `feat/port-console-features`로 옮겼다.

- `src/all_tomorrow/local_workers.py`는 두 브랜치에서 같다(`git diff` 결과 없음). 서버가 쓰는 `ADAPTERS`·`list_workers`·`load_config`와 `python -m all_tomorrow.local_workers --config … run <worker> --cwd … --project-id … --task-file …` 형식이 그대로라 이 부분은 바꾸지 않았다. 두 브랜치의 `adapters/workers.py` 차이는 `_allowlisted_env` 추가뿐이고, 이 함수는 아직 어디서도 호출되지 않는다.
- 바꾼 것: `subscription_usage`는 `all_tomorrow.usage`를 도구 안에서 import한다. 이 모듈이 없는 checkout에서도 서버와 나머지 도구는 뜨고, 이 도구만 `not available` 오류를 낸다.
- `pyproject.toml`: 의존성 `fastmcp>=4.0.5,<5`, 콘솔 스크립트 `all-tomorrow-mcp`·`all-tomorrow-usage`. `uv.lock`은 갱신하지 않았다(이전 브랜치도 갱신하지 않았고, CI·Docker는 `pip install`로 설치).

## 도구

`list_projects`, `register_project`, `project_status`(git 상태·최근 커밋·roadmap/README 앞부분), `list_local_workers`, `dispatch_task`, `get_run`, `list_runs`, `subscription_usage`.

- 프로젝트 목록: `config/projects.local.json` (Git 제외). 등록된 프로젝트 경로는 worker `allowed_roots`에 자동 포함된다. 프로젝트 패널 수집기(`all_tomorrow.projects_snapshot`)도 같은 파일을 읽는다.
- worker 설정: `config/workers.local.json` (Git 제외, 예시 `config/workers.example.json`). 두 로컬 파일은 서버를 띄우는 checkout에 있어야 한다. 경로는 `ALL_TOMORROW_PROJECTS`·`ALL_TOMORROW_WORKERS`·`ALL_TOMORROW_RUNS`로 바꿀 수 있다.
- 실행 기록: `.artifacts/mcp-runs/<run_id>/` (meta, task, argv, workers, result, stderr). 이 폴더가 각 실행의 유일한 원본이다.
- `SUCCESS`는 CLI 완료일 뿐이며, 요청한 변경이 실제로 성립했는지는 프로젝트 결과물로 다시 확인한다.
- `subscription_usage`는 콘솔 [구독 사용량 패널](usage-panel.md)과 같은 수집 함수(`usage.collect`)를 부른다.

## 실행 분리 (Windows)

MCP 클라이언트는 세션 종료 시 서버의 프로세스 트리를 정리한다. 관측 결과: 일반 detached 자식과 `CREATE_BREAKAWAY_FROM_JOB` 자식 모두 세션 종료와 함께 결과 없이 사라졌다(`INTERRUPTED`). WMI(`Win32_Process.Create`)로 만든 프로세스는 살아남아 결과를 남겼다. 정확한 종료 메커니즘(트리 kill 방식)은 확인하지 않았다.

## 등록

user scope 등록(2026-10-19, `~/.claude.json` mcpServers)은 이전 checkout을 가리킨다. 이번 이식에서 바꾸지 않았다.

```powershell
claude mcp add --scope user all-tomorrow -- C:/projects/all-tomorrow/.venv/Scripts/python.exe -m all_tomorrow.mcp_server
```

이 브랜치가 main에 합쳐진 뒤 `C:/projects/all-tomorrow`를 main으로 전환하면 같은 등록이 이식본을 실행한다. stdio 서버는 저장소 루트를 기준으로 동작하므로 그 checkout의 venv에 패키지(editable)와 `fastmcp`가 설치돼 있어야 하고, `config/*.local.json`이 있어야 한다.

## 검증 기록

### 이전 브랜치 (2026-10-19, `feat/stage-00d-close`)

- fastmcp stdio client로 8개 도구 노출 확인.
- `dispatch_task(all-tomorrow, codex)` → 세션 종료 후 재접속해 `get_run` → `SUCCESS`, 출력 `PONG`.
- `dispatch_task(eve-scene-runtime, codex)` → `SUCCESS`, 출력 `eve-scene-runtime` (다른 프로젝트 cwd에서 실행됨).
- `tests/test_mcp_server.py` 2개 통과.

### 이식본 (2026-10-19, `feat/port-console-features`)

- `tests/test_mcp_server.py` 5개 통과: 기존 2개, 가짜 Codex CLI로 `dispatch_task` → main의 `local_workers` CLI → 프로젝트 cwd에 파일 생성·`get_run` `SUCCESS`, `usage` 모듈이 없을 때 `subscription_usage`만 오류, in-memory client로 8개 도구 노출. 이 테스트에서는 detached spawn을 inline 실행으로 바꿨다.
- stdio 확인(테스트 밖, 1회): worktree에서 `python -m all_tomorrow.mcp_server`를 fastmcp stdio client로 띄움 → 8개 도구 노출. 12초 대기하는 가짜 Codex로 `dispatch_task` → `spawn: wmi`, `RUNNING` 상태에서 client 종료(이 시점 산출 파일 없음) → 20초 뒤 재접속해 `get_run` → `SUCCESS`, 출력 `PONG`. 산출 파일은 client 종료 뒤에 생겼다. `subscription_usage`는 이식 중인 `usage` 모듈로 `collected_at`·`providers`를 반환했다.
- 한계: 종료한 것은 Python fastmcp client이고 Claude 앱이 아니다. Claude 세션 종료 때의 프로세스 정리와 같은 조건인지는 확인하지 않았다. 이식본으로 실제 worker CLI를 실행하지는 않았다.

## 남은 일

- 이 브랜치 반영 후 Claude 세션에서 이식본 도구 호출 확인 (등록 경로 전환 포함)
- 실행 중 작업 취소 도구 없음
- run 상태는 pid 생존으로 판정한다. 결과 없이 끝난 run의 pid가 다른 프로세스에 재사용되면 `RUNNING`으로 잘못 보일 수 있다(이전 구현과 같음, 고치지 않음).

## 후속: 중앙 device-agent 큐를 거친 실행 (미착수)

지금 `dispatch_task`는 이 PC에서만 worker를 띄운다. main에는 tailnet의 중앙 서버(`all-tomorrow-central`, `http://100.97.113.3:8080`)에 Work를 쌓고 각 기기가 pull(claim → lease 갱신 → complete)하는 device agent가 있다([worker-adapters](worker-adapters.md)의 "Device agent (Tailscale)" 절). 다른 기기로 일을 보내려면 MCP가 프로세스를 직접 띄우는 대신 중앙 서버에 Work를 만들고, 실행 상태를 그 Work/lease에서 읽는 방향이 맞다. 그러면 `.artifacts/mcp-runs` 파일 대신 서버의 Work/lease가 실행의 원본이 되고, lease 만료 시 `ambiguous_side_effect`로 멈추는 규칙도 그대로 적용된다. 다만 현재 lease가 기기에 주는 작업 정보는 `title`뿐이고, 기기 쪽 client는 설정의 첫 worker를 자기 cwd에서 `project_id=None`으로 실행한다. 따라서 최소한 Work에 project id와 worker 지정을 싣고, 기기마다 project id → 로컬 경로 매핑을 두는 일이 먼저다. 이번 이식에서는 만들지 않는다.
