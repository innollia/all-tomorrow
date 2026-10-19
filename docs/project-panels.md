# 프로젝트 패널

- 상태: **개발중** — 이전 브랜치에서 공통 틀과 패널 9개 구현·로컬 검증 완료. main 콘솔로 이식 중. 중앙 서버 배포·수집기 주기 실행·wobnovel Tailscale 접속 설정 남음 (2026-10-19 사용자 요청)
- 범위: `C:\projects`의 각 프로젝트를 중앙 콘솔에서 보거나 그 프로젝트의 웹으로 이동한다. 필요 없어 보이는 프로젝트는 만들지 않는다.

## 이식 기록

처음 구현은 stale 브랜치 `feat/stage-00d-close`에서 했다. 이 브랜치는 main의 83개 커밋(Stage 1–3, device agent 포함) 이전에 갈라졌다. 2026-10-19 `feat/port-console-features`로 옮겼다.

- 콘솔: main의 섹션 셸(`/`, `static/console`)에 "프로젝트" 화면(`static/console/pages/projects.js`)으로 들어간다. 서버 라우터는 `all_tomorrow.console.projects`. 이전 대시보드는 `/requests`.
- 수집기 토큰: `ALL_TOMORROW_COLLECTOR_TOKEN` (없으면 `ALL_TOMORROW_USAGE_TOKEN`). 사용량 push와 같은 토큰이다.
- 서버: 이식 전에는 eve의 EC2 t4g.micro에 콘솔을 올린다고 가정했다. 이제 콘솔은 중앙 서버 `all-tomorrow-central`이 내준다(아래 서버 성능 원칙). eve 서버에 대한 측정값은 참고로 남겼다.
- 아래 패널 구현 결과·수집 시간·보안 사항은 모두 이전 브랜치에서 얻은 것이다. 이식본 화면은 아직 브라우저로 확인하지 않았다.

## 구조

| 부분 | 위치 | 하는 일 |
|---|---|---|
| 프로젝트 목록 | `config/projects.local.json` (Git 제외) | id, 경로, 메모, 링크. [MCP 서버](mcp-control.md)와 같은 파일 |
| 수집기 (이 PC) | `all_tomorrow.projects_snapshot` | git 사실, roadmap 상태표, 프로젝트별 플러그인 결과를 한 스냅숏으로 묶어 서버로 전송 |
| 플러그인 | `src/all_tomorrow/project_panels/<module>.py` | `PROJECT_IDS`, `collect(path)`. 읽기 전용, 네트워크·서버 실행 없음, 20KB 상한 |
| 패널 UI | `src/all_tomorrow/static/panels/<id>.js` | `window.AT_PANELS[id] = (panel, project, {esc, list, ago}) => html`. 그 프로젝트 화면을 열 때만 로드 |
| 서버 | `all_tomorrow.console.projects`: `POST /internal/projects` (Bearer 수집기 토큰), `GET /api/project-snapshot` (로그인) | 저장하고 그대로 내줄 뿐 계산하지 않음 |

```powershell
.venv/Scripts/python.exe -m all_tomorrow.projects_snapshot show [id]
$env:ALL_TOMORROW_URL="http://100.97.113.3:8080"; $env:ALL_TOMORROW_COLLECTOR_TOKEN="<서버와 같은 값>"
.venv/Scripts/python.exe -m all_tomorrow.projects_snapshot push
```

## 서버 성능 원칙

콘솔은 중앙 서버 `all-tomorrow-central`(tailnet, Linux, `http://100.97.113.3:8080`)이 내준다. 기기 연결은 [worker-adapters](worker-adapters.md)의 "Device agent (Tailscale)" 절, 배포 구성은 [deploy](deploy/aws-single-node.md). 중앙 서버도 단일 노드이므로 콘솔 기능은 요청마다 무거운 일을 하지 않는다(`all_tomorrow.console` 규약).

- 서버는 계산하지 않는다. git·DB·파일 읽기는 전부 이 PC의 수집기가 한다.
- 스냅숏은 받을 때 한 번 인코딩하고 ETag를 붙인다. 바뀌지 않았으면 304로 본문 없이 응답한다.
- 패널 JS는 해당 화면을 열 때만 받는다. 정적 파일은 브라우저 캐시를 쓴다.
- 콘솔 자동 갱신은 탭이 숨겨지면 멈춘다.
- 프로젝트 웹 서버를 이 서버에 같이 올리지 않는다(아래).
- 수집기: 프로젝트를 병렬로 읽고 git 호출마다 5초 상한. HEAD를 못 읽는 저장소는 `git status`를 건너뛴다. 손상된 TINProject 하나가 `git status`에만 20~30초를 써서 전체가 31초 걸리던 것이 3.4초(8개), 4초(15개)로 줄었다.

### 참고: eve 서버 (EC2 t4g.micro)

이식 전에는 콘솔을 이 서버에 올릴 계획이었다. 이 서버는 eve가 쓰는 서버이며, 아래는 2026-10-19에 측정한 사실이다.

- 사양: ARM aarch64, burstable 2 vCPU, RAM 904MB, EBS 8GB.
- 메모리: 가용 약 280MB, 스왑 1GB 중 약 500MB 사용 중. 상주 프로세스는 cloudflared(약 150~180MB), eve의 Antigravity `agy`(약 135MB), eve node 4개(약 220MB), PostgreSQL.
- 디스크: 100%(남은 64MB)였음 → 사용자 승인으로 apt 캐시·저널(50MB로 축소)·npm 캐시·이전 snap 정리, 남은 579MB(92%). eve·Discord 봇·PostgreSQL·cloudflared·Notion relay 모두 정상 확인.
- 당시 사용자 결정 "이 서버만 쓴다. 유료 업그레이드·EBS 확장·다른 클라우드 없음"은 콘솔을 이 서버에 올린다는 전제에서 나왔다. 콘솔이 중앙 서버로 정해진 지금 이 결정이 어디까지 적용되는지는 다시 확인하지 않았다.

## 프로젝트별 결정 (조사 2026-10-19)

| 처리 | 프로젝트 | 이유 |
|---|---|---|
| 패널 | TINProject, eve-scene-runtime, roblox-ugc-factory, wobnovel, video-factory, survey-copilot, money, innollia.github.io, snowday-orig | 활동 중이고 실행 없이 읽을 상태 데이터가 있음 |
| 링크만 | brainstorm-studio, risuai-prompt-parser, skill, flesh-pit, hugi-game | 앱을 여는 것이 쓸모의 전부이거나, 아직 데이터가 없음(flesh-pit은 동기화 중, 끝나면 패널 후보) |
| 없음 | 13th-age-rag-engine, DSR, RPG_project, T34-1941, all-tomorrow-opencode, character, everyric2_patched, gm_blank_test, income-research, manager-runtime, memos, nycko_ref, renpy, stone story rpg finetuning | 빈 폴더·자료 보관·휴면·남의 코드, 또는 개인/민감 내용이라 콘솔에 둘 이유가 없음 |

## 서버로 옮길지

2026-10-19 사용자 결정:

| 앱 | 결정 | 근거 |
|---|---|---|
| survey-copilot | 서버로 옮기지 않음 | 조사 결과 가능(standalone 60~100MB, WSL 빌드)했으나 인증 추가·데이터 이전 부담 대비 지금 필요 없음 |
| risuai-prompt-parser | 서버로 옮기지 않음 | 지금 필요 없음 |
| wobnovel | **PC에 둔다(PC를 켜 둠). 다른 기기에서는 Tailscale로 접속** | 집필이 PC의 Codex CLI·로컬 데이터·SQLite 하나에 의존. 서버 집필기는 API 호출 방식 신규 구현·이중 DB 동기화 문제 |

- 사용자 기기는 모두 Tailscale에 있다(사용자 확인, 2026-10-19). 같은 날 이 PC의 `tailscale status`에는 `all-tomorrow-central`을 포함해 5대가 보였다.
- wobnovel Tailscale 접속에 필요한 것(미착수): Studio의 `_StudioGuardMiddleware`가 localhost 이외 Host/Origin을 거부하므로 tailnet 주소(또는 MagicDNS 이름) 허용 설정 추가. Studio가 어느 주소에 바인드하는지는 확인하지 않았다. `bootstrap`이 세션 토큰을 내주므로 앞단 인증이 필요하다. tailnet 안에서는 tailnet 구성원과 ACL이 그 역할을 하므로, Funnel 같은 tailnet 밖 공개는 쓰지 않는다.

조사 당시 판단(참고):

- 새로 올릴 프로젝트는 없다고 판단한다.
  - eve-scene-runtime은 이미 EC2에서 돈다(같은 약한 서버를 이미 쓰고 있다).
  - wobnovel Studio, video-factory 보드는 로컬 AI CLI·로컬 파일에 의존한다.
  - survey-copilot은 설계상 로컬 전용(개인 수입·프로필).
  - risuai 파서에는 복호화된 유료 프리셋이 있어 공개하면 안 된다.
  - brainstorm-studio는 정적 빌드라 올릴 수는 있지만 데이터가 브라우저 IndexedDB(주소별)에 있어 주소를 옮기면 기존 보드가 안 보인다.
- 그래서 이 PC 전용 앱은 링크에 "이 PC에서만"을 표시해 둔다. 중앙 사이트는 연결만 하고, 프로젝트는 서버에 묶이지 않는다.

## 조사에서 나온 보안 사항 (값은 기록하지 않음)

사용자 결정이 필요하다. 아래는 아무것도 바꾸지 않았다.

| 위치 | 내용 | 권장 |
|---|---|---|
| `all-tomorrow/.git/config`, `eve-scene-runtime/.git/config` | origin 원격 주소에 GitHub 토큰이 박혀 있음(`git remote -v`로 출력됨). 각 워크트리도 공유 | 토큰 재발급, credential helper로 전환. 수집기는 원격 주소를 읽지 않는다 |
| `manager-runtime` | git 이력에 Notion 토큰 흔적, 민감 파일(성적 프로필 백업 등)이 추적됨. 저장소 공개 여부 미확인 | 공개 여부 확인, 토큰 재발급 |
| `wobnovel` (백업 브랜치) | 사이트 쿠키, Gemini 키 파일이 커밋·푸시됨 | 이력에서 제거, 재발급 |
| `RPG_project/api.py`, `stone story rpg finetuning/process_log.py` | Google API 키 하드코딩 (stone story는 Syncthing으로 다른 기기에도 복사됨) | 키 폐기 |
| `innollia.github.io` | `static/chronicle/data.json`(개인 메모 739건, 본문 375건)이 공개 사이트에 배포됨. 뷰어만 롤백되고 데이터는 남음 | 데이터 파일 제거 여부 결정 |
| `rpg-dungeon-master-bot` | Vite 설정이 API 키를 클라이언트 번들에 넣음 | 배포하지 말 것 |
| TINProject, flesh-pit | Syncthing이 `.git`까지 동기화해 HEAD 손상 | `.stignore`에 `.git` 추가 후 GitHub에서 다시 clone (사용자 동기화 설정 변경이라 하지 않았음) |

## 패널 구현 결과

| 패널 | 보여주는 것 | 수집 시간 |
|---|---|---|
| TINProject | 동기화 상태(진행 중이면 삭제 경보 보류), PRESENCE.md 감시, dryforge 사이클, 킷별 대기 질문, 모듈 상태, quote_vn·avatar_judge 점수 | 50~100ms |
| eve-scene-runtime | 게이트 상태, main/origin/desktop 브랜치·edge 워크트리(로컬 ref만), Discord 감사 로그 이벤트·실패율, 매니저 세션 사용률 | 0.2~0.3s |
| roblox-ugc-factory | 상태별 퍼널, 분류 대기열, 프로바이더 성공률, 최신 리포트, 최근 이벤트 | 약 8ms |
| wobnovel | status.md 최신 항목·미확인 수, Studio 실행·승인 대기, 작품별 회차 수 | 약 25ms |
| video-factory | 에피소드별 단계·QA 미해결·최종 mp4, 최신 검토 렌더 | 약 25ms |
| survey-copilot | 제안 상태·분당 기대수익 상위 3, 원장 합계, 브리지 대기 | 약 5ms |
| money | 작업표(상태·다음 행동), 실제 지원/판매/현금 합계, 기준일, 최신 보고서 | 약 3ms |
| innollia.github.io | 섹션별 글 수, chronicle 통계(본문 없음), 개인 메모 데이터 공개 경고 | 0.2s |
| Snow Day | TODO 완료/진행 수, 빌드 로그 결과, 대화 미리보기 존재 | 약 30ms |

- 모든 SQLite는 읽기 전용(`mode=ro`, 가능하면 `readonly_shm=1` — 일반 `mode=ro`는 아무도 DB를 열지 않은 상태에서 `-shm` 파일을 다시 써서 바꿈). 테스트로 파일 해시 불변 확인.
- 민감 필드(오류 원문·메모·원고·보고서 본문·프로필·Discord 내용·원격 주소)는 읽지 않거나 보내지 않으며, 테스트가 표식 문자열로 확인.
- 각 패널 JS는 node로 실제 데이터·빈 데이터·HTML 주입 값에 대해 렌더 확인. 브라우저 화면 확인은 아직.

## 남은 일

- 중앙 서버에 이 브랜치 배포, `ALL_TOMORROW_COLLECTOR_TOKEN` 설정
- 수집기 주기 실행 등록, 중앙 서버로 push → 콘솔 표시를 브라우저로 확인
- wobnovel Tailscale 접속 설정(위)
- flesh-pit 동기화가 끝나면 패널 여부 재판단
