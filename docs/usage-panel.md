# 구독 사용량 패널

- 상태: **개발중** — 이전 브랜치에서 로컬 수집·대시보드 렌더링 검증 완료. main 콘솔로 이식 중이며 중앙 서버 배포·주기 push는 미완료.
- 범위: 2026-10-19 사용자 요청. Claude/Codex 구독 사용량(5시간·주간 창)을 콘솔에 표시한다. Stage 표와 별개인 콘솔 기능이다.

## 이식 기록

처음 구현은 stale 브랜치 `feat/stage-00d-close`에서 했다. 이 브랜치는 main의 83개 커밋(Stage 1–3, device agent 포함) 이전에 갈라졌다. 2026-10-19 `feat/port-console-features`로 옮겼다.

| | 이전 브랜치 | 이식본 |
|---|---|---|
| 화면 | `web.py` 문자열 HTML 대시보드 상단 | 콘솔(`/`, `static/console`)의 "모니터링 › 구독 사용량" (`static/console/pages/usage.js`) |
| 서버 라우터 | `web.py` | `all_tomorrow.console.usage` |
| 저장 위치 | `ALL_TOMORROW_USAGE_PATH` (기본 `.artifacts/usage.json`) | 콘솔 feature 디렉터리 `ALL_TOMORROW_CONSOLE_DATA`(기본 `.artifacts/console`)의 `usage/usage.json` |
| push 토큰 | `ALL_TOMORROW_USAGE_TOKEN` | `ALL_TOMORROW_COLLECTOR_TOKEN` (없으면 `ALL_TOMORROW_USAGE_TOKEN`). 프로젝트 스냅숏 push와 같은 수집기 토큰 |
| 서버 | AWS 서버 (주소 미기재) | 중앙 서버 `all-tomorrow-central` (아래) |

main의 이전 대시보드는 `/requests`로 옮겨졌다. 상태 줄의 "렌더링 검증"은 이전 브랜치 화면 기준이며, 이식본 화면은 아직 브라우저로 확인하지 않았다.

## 구조

로그인 정보는 이 PC에만 있으므로 중앙 서버가 직접 조회하지 않는다. 이 PC의 collector가 credential 없는 snapshot만 서버로 보낸다.

- 수집: `all_tomorrow.usage` — Claude는 `~/.claude/.credentials.json`의 OAuth token으로 Anthropic usage endpoint 조회(만료 시 갱신하지 않고 `token_expired` 표시). Codex는 `~/.codex/sessions`의 최신 `rate_limits` 기록을 읽는다. Codex 값은 마지막 Codex 실행 시점 기준이며, 관측 시점이 30분보다 오래되면 콘솔에 "N시간 전 관측값"처럼 표시된다.
- 서버: `POST /internal/usage` (Bearer 수집기 토큰, edge token과 별개), `GET /api/usage` (로그인 필요). 최신 snapshot은 파일로 저장되어 재시작 후에도 유지된다.
- 중앙 서버: tailnet의 `all-tomorrow-central` (Linux, `http://100.97.113.3:8080`). 기기 연결은 [worker-adapters](worker-adapters.md)의 "Device agent (Tailscale)" 절, 배포 구성은 [deploy](deploy/aws-single-node.md).
- 같은 수집 결과를 MCP 도구 `subscription_usage`로도 볼 수 있다([MCP 연결](mcp-control.md)).

```powershell
.venv/Scripts/python.exe -m all_tomorrow.usage show
$env:ALL_TOMORROW_URL="http://100.97.113.3:8080"; $env:ALL_TOMORROW_COLLECTOR_TOKEN="<서버와 같은 값>"
.venv/Scripts/python.exe -m all_tomorrow.usage push
```

## 남은 일

- 중앙 서버에 `ALL_TOMORROW_COLLECTOR_TOKEN` 설정 후 이 브랜치 배포
- 이 PC에서 push 주기 실행(예: 작업 스케줄러 5분 간격) 등록
- 중앙 서버로 push → 콘솔 표시 확인
