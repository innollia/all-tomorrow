# 구독 사용량 패널

- 상태: **개발중** — 로컬 수집·대시보드 렌더링 검증 완료, AWS 배포·주기 실행 미완료
- 범위: 2026-10-19 사용자 요청. Claude/Codex 구독 사용량(5시간·주간 창)을 웹 대시보드 상단에 표시한다. Stage 0 gate의 한정 예외이며 Stage 2 web ingress 완료를 뜻하지 않는다.

## 구조

로그인 정보는 이 PC에만 있으므로 AWS 서버가 직접 조회하지 않는다. 이 PC의 collector가 credential 없는 snapshot만 서버로 보낸다.

- 수집: `all_tomorrow.usage` — Claude는 `~/.claude/.credentials.json`의 OAuth token으로 Anthropic usage endpoint 조회(만료 시 갱신하지 않고 `token_expired` 표시). Codex는 `~/.codex/sessions`의 최신 `rate_limits` 기록을 읽는다. Codex 값은 마지막 Codex 실행 시점 기준이며 대시보드에 "N시간 전 관측값"으로 표시된다.
- 서버: `POST /internal/usage` (Bearer `ALL_TOMORROW_USAGE_TOKEN`, edge token과 별개), `GET /api/usage` (로그인 필요). 최신 snapshot은 `ALL_TOMORROW_USAGE_PATH`(기본 `.artifacts/usage.json`)에 저장되어 재시작 후에도 유지된다.

```powershell
.venv/Scripts/python.exe -m all_tomorrow.usage show
$env:ALL_TOMORROW_URL="https://<서버>"; $env:ALL_TOMORROW_USAGE_TOKEN="<서버와 같은 값>"
.venv/Scripts/python.exe -m all_tomorrow.usage push
```

## 남은 일

- AWS 서버에 `ALL_TOMORROW_USAGE_TOKEN` 설정 후 재배포
- 이 PC에서 push 주기 실행(예: 작업 스케줄러 5분 간격) 등록
- 실제 AWS URL로 push → 대시보드 표시 확인
