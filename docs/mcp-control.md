# Claude → All Tomorrow MCP 연결

- 상태: **개발중** — 서버·도구·실제 worker 실행 검증 완료, Claude user scope 등록 완료(2026-10-19, `~/.claude.json` mcpServers). 새 Claude 세션에서의 실제 호출 확인 전
- 범위: 2026-10-19 사용자가 Stage 0 gate 예외를 승인. Claude 세션이 All Tomorrow에 붙어 등록된 프로젝트를 보고 로컬 worker에 작업을 맡긴다. 이 PC 로컬(stdio) 전용이며 AWS 웹/원격 접속, durable queue, 자동 worker 선택은 포함하지 않는다.

## 도구

`list_projects`, `register_project`, `project_status`(git 상태·최근 커밋·roadmap/README 앞부분), `list_local_workers`, `dispatch_task`, `get_run`, `list_runs`, `subscription_usage`.

- 프로젝트 목록: `config/projects.local.json` (Git 제외, 예시는 `projects.example.json`). 등록된 프로젝트 경로는 worker `allowed_roots`에 자동 포함된다.
- 실행 기록: `.artifacts/mcp-runs/<run_id>/` (meta, task, argv, result, stderr). 이 폴더가 각 실행의 유일한 원본이다.
- `SUCCESS`는 CLI 완료일 뿐이며, 요청한 변경이 실제로 성립했는지는 프로젝트 결과물로 다시 확인한다.

## 실행 분리 (Windows)

MCP 클라이언트는 세션 종료 시 서버의 프로세스 트리를 정리한다. 관측 결과: 일반 detached 자식과 `CREATE_BREAKAWAY_FROM_JOB` 자식 모두 세션 종료와 함께 결과 없이 사라졌다(`INTERRUPTED`). WMI(`Win32_Process.Create`)로 만든 프로세스는 살아남아 결과를 남겼다. 정확한 종료 메커니즘(트리 kill 방식)은 확인하지 않았다.

## 검증 기록 (2026-10-19)

- fastmcp stdio client로 8개 도구 노출 확인.
- `dispatch_task(all-tomorrow, codex)` → 세션 종료 후 재접속해 `get_run` → `SUCCESS`, 출력 `PONG`.
- `dispatch_task(eve-scene-runtime, codex)` → `SUCCESS`, 출력 `eve-scene-runtime` (다른 프로젝트 cwd에서 실행됨).
- `tests/test_mcp_server.py` 2개 통과.

## 남은 일

- 새 Claude 세션에서 도구 호출 확인. 등록 방식(CLI 동등):
  `claude mcp add --scope user all-tomorrow -- C:/projects/all-tomorrow/.venv/Scripts/python.exe -m all_tomorrow.mcp_server`
  (stdio 서버는 저장소 루트를 기준으로 동작하므로 `-m` 실행 시 venv에 패키지가 설치돼 있어야 한다)
- 실행 중 작업 취소 도구 없음, 다른 PC/AWS에서의 원격 통솔 없음
