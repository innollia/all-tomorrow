# 서버 대시보드 — 호스트와 서비스

상태: **개발중** (구현·자동시험·DP7 실측 완료, 시각 검증·운영 반영 대기).
작업일: 2026-10-24. 커밋하지 않음.

## 사용과 배포

로그인 후 `/#/servers`. 메뉴: 모니터링 → 서버. 행 또는 서비스 링크를 누르면 `/#/servers/<id>` 상세로 이동한다. API는 로그인 보호된 `GET /api/servers`.
기존 feature 자동 mount를 사용한다. 실행 중인 API에는 새 Python 모듈 로드를 위한 재시작이 필요하다. 이번 작업에서는 운영 API·예약 작업을 재시작하거나 변경하지 않았다.
정본 `config/infrastructure.json`에 비밀 없이 호스트 4대·서비스 21개를 등록했다. API는 저장소 루트의 config를 읽으므로 배포 시 함께 제공한다. 변경 반영에는 재시작이 필요하며 잘못된 등록부는 시작 시 거부한다.

## 관측 의미

- HTTP 2xx는 확인됨, 비정상 HTTP·연결 실패는 이상 관측. 응답 본문·헤더·오류 원문은 반환하지 않고 redirect는 따라가지 않는다.
- TCP는 첫 번째 등록 포트 연결만 점검한다. Syncthing 8384 확인은 22000 동기화 정상의 증거가 아니다.
- 로컬 Windows 작업은 Running 또는 Ready+실행 이력+마지막 결과 0을 구별해 설명한다. Ready는 현재 실행 중이라는 뜻이 아니다. 프로세스 패턴 점검도 지원한다.
- 초기 등록부 작업 이름은 scripts/dp7-up.ps1에 근거한다. 명령·자격증명·프로세스 명령줄은 응답에 포함하지 않는다.
- 권한 부족, 방법 미등록, 원격 TCP/프로세스/Windows 작업, 원격 loopback URL은 미확인이다. 원격 systemd 실행을 추측하지 않는다.
- 호스트는 등록 서비스 요약이다. 이상이 있으면 이상, 그 외 미확인이 하나라도 있으면 미확인이다. 컴퓨터 자체 장애·기능 전체 정상으로 일반화하지 않는다.
- 서버 실제 hostname과 host_id가 같을 때만 로컬 점검한다. AWS 배포 시 DP7의 127.0.0.1을 AWS 자신의 포트로 오인하지 않는다.
- 병렬도 6, HTTP/TCP 타임아웃 1.5초, Windows 명령 4초. 30초 캐시와 lock으로 동시 요청을 합친다. 읽기 전용이다.

## DP7 실측

동일 Dashboard 프로브를 직접 실행했다. 상태는 관측 시점에 한정한다.

| 서비스 | 결과 | 근거 |
|---|---|---|
| All Tomorrow API | 확인됨 | 127.0.0.1:5476/healthz HTTP 200 |
| Postgres 18 | 확인됨 | TCP 5432 |
| LiteLLM 무료 게이트웨이 | 확인됨 | TCP 4000 |
| Syncthing (DP7) | 확인됨 | TCP 8384 |
| OpenCode serve | 확인됨 | TCP 45278 |
| Caddy + Snow Day | 확인됨 | 공개 사이트 HTTP 200 |
| api-watchdog / executor / overseer / activity / collect / StudyGame-DailyPost | 미확인 | Windows 작업 조회 불가 (권한·작업 존재 여부 구분 불가) |
| excalidraw MCP | 미확인 | agent-stdio 수명 종속, 확인 방법 미등록 |
| aaaa Syncthing / collect-only | 미확인 | 원격 조회 방법 미등록 |
| eve-discord-bot / eve-discord-cache / eve-manager-antigravity / eve-scene-notion-relay | 미확인 | systemd 원격 조회 방법 미등록 |
| eve-scene-runtime | 미확인 | 원격 loopback /healthz 접근 불가 |
| All Tomorrow 콘솔 사본 | 미확인 | 존재·배포 미확인 |

총 **확인됨 6 / 이상 관측 0 / 미확인 15**. 호스트 4대 모두 미확인 서비스를 포함하므로 미확인이다.

## 검증

- 신규 시험 22개 + 기존 console shell 3개: **25 passed**.
- 전체 **824 passed / 69 skipped / 1 failed**. 기존 tests/test_workers.py::TestRealCliSmoke::test_opencode_cli_help_smoke의 외부 npx opencode-ai 실행 실패다. 기존 roadmap에도 기록된 실패이며 시험을 생략·수정하지 않았다.
- 등록부 중복 ID·host 참조·포트·비밀 포함 URL·누락 target·알 수 없는 필드, HTTP/TCP 성공·실패, 원격 loopback·방법 없음, Windows 결과·조회 오류, 캐시·동시 요청·만료, 비로그인 거부·로그인 응답·feature 장착을 시험했다.
- node --check 및 git diff --check 통과.
- 기본 pytest 임시 경로 PermissionError로 쓰기 가능한 scratchpad를 --basetemp와 cache_dir로 지정했다. Python은 지시서의 DP7 runtime을 사용했다.
- 기존 콘솔 토큰, 가로 스크롤 표, 480px 이하 단일 카드 열, 긴 주소 줄바꿈, 키보드 링크를 적용했다. **시각 검증은 미확인**: CUA iab 생성 300초 시간 초과, Chrome headless 데스크톱/모바일 실행은 종료 코드 2147483651로 실패했다.
- jev-review-gate 외부 checkout이 없어 결정적 diff·시험 점검을 적용했다.

재현: 지시서 Python으로 `-m pytest -q --basetemp=<새 쓰기 가능 경로> -o cache_dir=<쓰기 가능한 캐시 경로>`.

남은 일: 실제 브라우저 1280px/390px 화면·서비스 상세·가로 스크롤 확인, 관제 커밋/배포 후 API 재시작·로그인 경로 확인. 이 조건 전에는 개발완료로 올리지 않는다.
