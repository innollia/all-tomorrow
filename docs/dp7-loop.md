# DP7 자기개선 고리

상태: **개발중**. 코드와 InMemory 고리 시험이 있으며, 실제 Postgres·Discord·재부팅 뒤 운영은 확인 전이다. 예약 작업 등록 스크립트는 이번 작업에서 실행하지 않았다. 사용자가 아무 요청을 하지 않았는데 발견·수정 보고가 디스코드에 도착해야 실제 운영 완료다.

## 2026-10-21 Work 실패·무변경 깨어남 보정

상태: **개발중**. 코드 수정·로컬 회귀 검증 후, 관제의 재등록과 실제 Work 성공·재기동 검증을 기다린다. 운영 예약 작업과 기존 실패 Work는 변경하지 않았다.

- **확인:** runtime의 `force=True`가 무변경 검사를 무시했다. 이를 제거하고 직전 판단의 `metacog.wake_applied`도 새 근거에서 제외했다. 열린 PENDING/RUNNING Work와 새 실패·세션·카드·질문·중앙 이벤트는 계속 판단한다. 사용량 스케줄은 간격만 정한다.
- **확인:** CLI 실패 결과가 버려졌고 adapter 예외·편집안 파싱 오류는 다음 작업자 시도를 중단했다. 작업자별 실패를 기록하고 fallback을 이어가며, 성공 응답만 있고 변경 파일이 없어도 실패로 처리한다. 무료 모델의 JSON 예시도 올바른 문법으로 고쳤다. 부분 편집은 다음 작업자에게 넘기지 않는다.
- **실제 재현/한계:** Codex adapter는 현재 sandbox에서 exit 1 / `Could not find home directory`로 종료했다. 운영 중 두 Work의 Codex 실패와 같은 원인인지는 미확정이다. agy는 PATH에서 발견되지 않았으며 기존 탐색에 없던 `Microsoft/WinGet/Links/agy.exe`를 추가했다. PowerShell은 설치 경로를 보지만 sandbox의 Python lstat은 WinError 5로 거부돼 실제 agy 실행은 미확인이다. 임시 WinGet 경로 탐색 시험은 통과했다. CLI 권한 경계는 유지했다([OpenAI CLI 옵션 문서](https://learn.chatgpt.com/docs/cli/reference)).
- **추론/미확정:** 기존 executor.log의 gateway HTTP 200과 최종 LLMError는 `apply_edits → parse_json`의 JSON 파싱 실패 경로에 부합한다. 응답과 앞 CLI 오류가 유실돼 구체적 원인을 소급 확정할 수 없다. 운영 `execute_pending` 호출자는 runtime executor 분기 하나이고 두 요청이 executor.log에 있으므로 executor 경로 실행이 근거에 맞는다. 당시 예약 작업 인스턴스/PID·보고된 `0xC000013A`의 종료 원인은 미확정이다. 예약 작업·프로세스 명령줄·TaskScheduler 이력 조회가 sandbox에서 제한됐다.
- **진단:** 종료 코드·가린 stderr/오류 요약·시간 초과·작업/심사/시험/반영 단계는 executor.log, 사본 옆 `worker-attempts.json`, `metacog.execution_attempt` 및 run_finished/rolled_back/applied payload에 남긴다. 보고에도 요약하며 재시작 복구는 보관된 진단을 Event/보고로 옮긴다. 시험 출력은 임시 파일에서 가린 끝부분만 보관한다. runtime 시작과 run_started에 PID/부모 PID도 기록한다.
- **등록/언어:** executor·overseer는 Interactive/Limited와 1분 반복 재기동 트리거를 사용한다. 기존 무제한 실행·실패 재시작·IgnoreNew·파일 singleton은 유지하며 API·collect는 S4U다. 한국어 지시는 기존에도 있었으며 모든 자연어 필드와 중국어 표현의 번역을 더 명시했다. 실제 언어 준수·로그인/재부팅 뒤 유지 여부는 다음 운영 검증 대상이다.

최종 시험: 신규 회귀 **19건**, 관련 **64 passed**. 전체 DP7 Python 실행 **747 passed, 69 skipped, 1 failed**(79.47초). 실패는 기존 `test_opencode_cli_help_smoke` 외부 npx 실행이며 Antigravity smoke는 PATH에서 찾지 못해 skip됐다. 원본은 `.artifacts/pytest-hands-full.txt`다. 지정 `.venv/Scripts/python.exe`는 `Unable to create process using`으로 시작조차 못 해 기존 DP7 Python으로 실행했다. venv 설정과 테스트 skip 조건은 변경하지 않았다. Jev 외부 검토 checkout이 없어 diff·회귀시험으로 검토했다. 커밋하지 않았다.

관제 명령(관리자 PowerShell, 진행 중 Work가 있으면 종료 후 실행):

```powershell
Set-Location C:\projects\all-tomorrow
'executor','overseer' | ForEach-Object { Stop-ScheduledTask -TaskName "AllTomorrow-DP7-$_" }
.\scripts\dp7-up.ps1
Get-ScheduledTask -TaskName 'AllTomorrow-DP7-executor','AllTomorrow-DP7-overseer' |
    Select-Object TaskName,State,@{n='LogonType';e={$_.Principal.LogonType}}
Get-Content "$env:USERPROFILE\.all-tomorrow\overseer\executor.log" -Tail 30
```

이전 프로세스를 재시작해야 코드가 적용된다. 다음 Work의 진단, 중단 뒤 1분 트리거의 재기동, 무변경 때 Codex 미호출을 확인한다. 기존 실패 Work를 자동 재실행하지 않는다.

메타인지는 Codex로 판단하고 기존 `validate_decision`과 `DecisionMaterializer`로 Goal/Work를 만든다. 별도 실행기가 기존 CLI adapter를 Codex → Antigravity → 무료 gateway(`g-fast`) 순으로 사용한다. Kiro·OpenCode·노트북은 이 고리의 작업자가 아니다. 사용자 개별 세션의 직접 요청은 새 Work로 복제하지 않는다.

## 저장과 경계

- 정본은 기존 PostgreSQL Goal/Work/Run/Event다. 판단 근거, 문제 키의 fingerprint, 스냅샷 ID, lineage, 시험 명령, 결과, 보고를 Event에 남긴다. 새 큐나 lease는 없다. 일반 device agent는 검증 실행기가 맡은 Work를 가져가지 않는다.
- DB advisory transaction 안에서 중복과 하루 생성 예산을 확인하고 Goal/Work/Event를 함께 저장한다. 기존 lineage fingerprint/BudgetLedger를 재사용한다. 시작 예산은 UTC 하루 96건, DP7 실행기는 한 번에 한 작업이다. 같은 문제 키는 완료 뒤에도 중복 생성하지 않는다. 재발이면 이전 결과를 근거로 새 문제 키를 판단한다.
- `projects.local.json`에 등록되고 이 PC에 존재하는 폴더만 대상이다. `autonomy.verify_argv`가 있으면 그 고정 시험을 쓴다. 없으면 메타인지가 프로젝트를 읽어 시험 명령을 판단하고 Work를 만들 때 고정한다. 운영 시험 선정 때문에 사용자에게 묻지 않는다. 명령이나 대상이 바뀌면 옛 권한을 재사용하지 않는다. 실제 시험 명령도 반영 전 Codex 심사에 포함한다.
- 권한·비용 확대, 사용자 자료 삭제, 창작 방향 선택, 불명확한 분류는 질문 Event와 디스코드 보고로 남기고 실행하지 않는다. 이 고리는 보호 변경 승인 기능을 추가하지 않는다. 디스코드 답장만으로 보호 변경을 승인할 수 없다.

## 커밋 없는 시험과 되돌림

`~/.all-tomorrow/overseer/changes/<work_id>/before`에 현재 파일을 복사한다. 미커밋 변경도 그대로 보존한다. `.git`, 환경 파일, 비밀 파일, 가상환경·캐시는 사본에서 제외한다. 링크가 있는 프로젝트는 자동 변경하지 않는다.

작업자는 `candidate` 사본에서 고친다. Codex는 workspace-write sandbox를 사용하고 허용 작업 폴더는 이 사본 하나다. Antigravity는 plan 모드에서 편집안을 반환하며 실행기가 경로를 검사해 사본에만 쓴다. 무료 모델도 같은 파일 편집안 형식을 쓴다. 일반 변경 여부는 Codex가 실제 diff를 다시 심사한다. 기존 시험·설정·배포·제어 경계의 수정은 자동 반영하지 않는다.

시험을 통과한 사본만 반영한다. 원본 해시가 달라졌으면 덮어쓰지 않는다. 반영 전 `promotion.json`에 이전/후보 해시를 기록하고, 파일별 교체 뒤 실제 바이트를 비교한다. 실패하면 이전 바이트로 복구하고 새로 만든 파일은 삭제 대신 `reverted-new`로 옮겨 둔다. 실행이 중단돼도 다음 실행기가 manifest를 읽어 부분 반영을 되돌린다. 다른 세션의 변경과 충돌하면 덮어쓰지 않고 질문한다. 백업과 후보는 자동 삭제하지 않는다. git 커밋·reset·clean은 쓰지 않는다.

Run/Work/Goal 결과와 보고 Event는 같은 트랜잭션으로 확정한다. 다음 메타인지 스냅샷은 이 결과를 포함한다. 판단 일지 저장 뒤 중앙 저장 전에 중단된 경우에도 다음 실행에서 행동을 다시 읽어 중복 없이 저장한다.

보고는 `overseer/reports/*.json`에 먼저 쌓는다. 기본 전달자는 기존 Eve 봇이며, 꺼져 있으면 파일에 남는다. Eve가 15초마다 기존 edge 인증으로 `/internal/edge/discord/reports`를 읽어 사용자 DM에 나눠 보내고, 메시지 ID와 성공한 부분을 `/reports/ack`로 기록한다. Event ID가 파일과 메시지에 남아 같은 결과를 식별한다. Discord nonce도 쓰지만 전송 직후 기록 전에 중단되고 오래 뒤 재시도하면 중복이 올 수 있다. 기존 webhook은 `ALL_TOMORROW_DISCORD_TRANSPORT=webhook`을 명시한 때만 쓴다.

Eve는 사용자 말의 의미를 기존 Groq 모델로 먼저 판단하고 중앙 권한·공유 상태가 필요한 말만 기존 `/internal/edge/discord/decide`에 보낸다. 중앙 요청은 웹 로그인 소유자의 Goal/Work에 저장되고 사용자에게 Goal ID를 요청 번호로 돌려준다. 일상 대화는 기존 페르소나·DM 에이전트가 처리한다. 보고 메시지에 Discord **답장**하면 원래 Event ID에 `discord.question_reply`가 이어지고 다음 메타인지 스냅샷에도 포함된다. 답변 기록은 승인이 아니며 Work 상태를 바꾸거나 실행을 재개하지 않는다. 권한·비용 확대는 웹 콘솔의 기존 승인 경계를 이용한다.

## 사용량과 PC 사용 여부

Codex는 [공식 app-server의 account/rateLimits/read](https://learn.chatgpt.com/docs/app-server)로 현재 잔량과 초기화 시각을 읽는다. 실패하면 로그를 쓰되 Syncthing 파일 수정 시각보다 실제 관측 시각을 우선한다. 오래된 관측값으로 메타인지를 깨우지 않는다. Claude의 만료 access token은 기존 refresh token으로 갱신하고 CLI가 도중에 새로 로그인한 값은 덮어쓰지 않는다. 갱신 불가 시 재로그인 질문을 쌓는다. 토큰 값이나 오류 응답 본문은 보고하지 않는다.

PC가 5분 이상 미사용이고 Codex 잔량이 확인되면 초기화까지 남은 시간/잔량에 맞춰 간격을 정한다(최소 1분, 최대 30분). 미사용 시간은 [Windows 사용자 세션의 LastInputTime](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/ns-wtsapi32-wtsinfow)을 읽는다. WTS가 이 값을 제공하지 않는 로컬 세션은 로그인 때 뜨는 activity 작업이 입력 시각을 파일로 전달한다. 관측할 수 없으면 보류한다. 실제 사용량 소진 효율은 상시 운영 뒤 조정해야 한다.

## 사용자가 준비할 것

Postgres 18 서비스 안에 전용 계정과 DB를 만든다. 예: 관리자 `psql`에서 `CREATE ROLE all_tomorrow LOGIN;`, `\password all_tomorrow`, `CREATE DATABASE all_tomorrow OWNER all_tomorrow;` 순서로 실행한다. 비밀번호는 프롬프트에서 넣는다. 기존 DB나 자료를 지우지 않는다.

`~/.all-tomorrow/key-pool.env`에 다음 **이름**으로 값을 넣는다. 값은 문서나 채팅에 붙이지 않는다.

| 이름 | 용도 |
|---|---|
| `ALL_TOMORROW_DATABASE_URL` | 전용 계정의 `postgresql://…@127.0.0.1:5432/all_tomorrow` 연결 문자열 |
| `ALL_TOMORROW_ADMIN_USER` | 웹 로그인 이름 |
| `ALL_TOMORROW_ADMIN_PASSWORD` | 웹 로그인 비밀번호 |
| `ALL_TOMORROW_SESSION_SECRET` | 충분히 긴 무작위 세션 서명값 |
| `ALL_TOMORROW_EDGE_TOKEN` | 기존 기계용 edge 토큰. Eve와 중앙에 같은 값을 설정 |
| `DISCORD_OWNER_USER_ID` | 보고·질문과 중앙 요청을 허용할 사용자 한 사람의 Discord ID. 중앙과 Eve에 동일하게 설정 |
| `ALL_TOMORROW_DISCORD_TRANSPORT` | 기본 `eve`. 기존 webhook을 별도로 쓸 때만 `webhook` |
| `ALL_TOMORROW_COLLECTOR_TOKEN` | 웹 사용량 패널에 주기 push할 수집기 토큰 |
| `IDEA_FACTORY_GATEWAY_KEY` | 이미 쓰는 무료 gateway master key |

Codex·Antigravity CLI 로그인도 이 PC 사용자 계정에 있어야 한다. 무료 gateway는 기존 key pool과 `config/idea-factory.yaml`을 사용한다. 새 유료 모델이나 계정은 추가하지 않는다.

## 관제가 실행할 명령

Eve `.env`에는 기존 `DISCORD_TOKEN`·`DISCORD_GUILD_ID`·`DISCORD_FORUM_ID`를 유지하고 `DISCORD_OWNER_USER_ID`와 중앙과 같은 `ALL_TOMORROW_EDGE_TOKEN`을 넣는다. 현재 사용자 ID는 없다. `ALL_TOMORROW_URL`은 기본 `http://127.0.0.1:5476`이며, `ALL_TOMORROW_DISCORD_THREAD_ID`를 지정하지 않으면 DM이다. 중앙 key-pool에도 사용자 ID와 edge 토큰을 넣는다. 예전 Eve 봇은 AWS `/home/ubuntu/eve-discord-runtime` 배포 기록이 있으므로 DP7 시작 전 기존 실행 여부를 관제가 확인한다. 두 곳에서 동시에 켜지 않는다.

관리자 PowerShell에서 저장소로 이동한 뒤 실행한다. 스크립트는 자체 실행하지 않았다.

```powershell
Set-Location C:\projects\all-tomorrow
.\scripts\dp7-up.ps1
.\scripts\dp7-eve-up.ps1
```

기본 Python은 `~/.all-tomorrow/dp7-runtime/Scripts/python.exe`다. 다른 정상 환경이면 `-Python <python.exe의 절대경로>`를 붙인다. 이번 검증용 환경은 이 PC의 Python 3.14와 기존 `.venv/Lib/site-packages`를 재사용한다. Syncthing 가상환경의 launcher는 실행되지 않아 그대로 보존했다. 독립 배포 환경은 해당 PC에서 프로젝트 의존성을 새로 설치해 `-Python`으로 지정할 수 있다.

스크립트는 제한된 사용자 권한으로 API·실행기·메타인지·수집 작업을 부팅/로그인 때 재시작하고, 사용자 입력 관측은 로그인 세션에서 실행한다. 비밀값은 task 명령줄에 넣지 않고 매 시작 때 key-pool을 읽는다. API는 127.0.0.1:5476이며 기존 Tailscale Serve 연결을 이용한다. 실제 등록 후에는 `Get-ScheduledTask -TaskName 'AllTomorrow-DP7-*'`와 `~/.all-tomorrow/overseer/*.log`, 폰 로그인, 자발적 Discord 보고를 확인한다.

## 검증 기록

전체 테스트 수치는 이번 작업 종료 기록과 `docs/overseer-plan.md`를 따른다. Postgres 시험은 `AT_TEST_POSTGRES_URL`이 있을 때만 실행한다. 실계정 OAuth 갱신, 상시 서비스 등록, 실제 Discord 전송, 재부팅 복구는 사용자 설정 전이라 확인하지 않았다. 현재 Codex 도구 sandbox 안의 하위 app-server는 홈 디렉터리 접근 문제로 조기 종료했다. 밖에서 등록한 DP7 작업에서 다시 확인해야 한다.

2026-10-21 최종 결과: 관련 시험 **89 passed**. 전체 `python -m pytest -q`는 **720 passed, 69 skipped, 1 failed**(76.15초). 실패는 `test_workers.py::TestRealCliSmoke::test_opencode_cli_help_smoke`다. 원본 결과는 `.artifacts/pytest-loop-final.txt`에 있다. PowerShell 구문 분석, Python 컴파일, `git diff --check`도 통과했다. 실행 Python은 `~/.all-tomorrow/dp7-runtime/Scripts/python.exe`이며, sandbox 권한에 맞춰 TEMP/TMP와 pytest/npm 캐시만 `.artifacts` 아래로 지정했다. npm 설치 스크립트는 smoke 확인에서 끄고 실제 help 실행은 그대로 시도했다.

OpenCode는 이 실행기의 작업자가 아니지만 기존 전체 테스트에 CLI smoke가 남아 있다. 이번 환경에서는 npm 기본 캐시 접근과 postinstall 실행이 실패했고, 별도 캐시에서 설치 스크립트를 끈 뒤에도 바이너리가 Windows에서 실행되지 않아 해당 smoke 1건이 실패했다. 테스트를 제거하거나 skip으로 바꾸지 않았다. 기존 Antigravity smoke는 이번 PATH에서 CLI를 찾지 못해 skip됐다. 처음 지시서에 기록된 Antigravity timeout과 다른 환경 결과다.

Windows timeout 시 `taskkill /T`가 접근 거부로 실패하는 것도 실제 시험에서 확인했다. 기존 worker adapter에 해당 실행만 묶는 Job Object를 연결해 자식 프로세스까지 종료하도록 고쳤으며, 기존 descendant 종료 시험을 통과했다. Jev 외부 검토 도구는 지정된 checkout/자격 정보가 없어 실행하지 않았고, 변경 diff·실제 파일 시험·오류 복구·전체 테스트로 검토했다.

## 이번 변경 파일

Eve 연결 추가분: 중앙 `src/all_tomorrow/overseer/{discord_edge,reports,loop}.py`, `src/all_tomorrow/web.py`, `scripts/dp7-eve-{up,run}.ps1`, `tests/{test_eve_discord_edge,test_overseer_loop}.py`, `config/key-pool.example.env`, 이 문서·관제 진행 기록·전체/Stage 1/보고 packet 인덱스. Eve는 `src/discord/{all-tomorrow-bridge,bot-agent-v3,bot,config}.mjs`, `test/all-tomorrow-bridge.test.mjs`, `.env.example`, `docs/DISCORD_BOT_GUIDE.md`다. 기존 미커밋 작업은 보존했다.

2026-10-21 Eve 연결 검증: 관련 Python **24 passed**, Eve 가짜 클라이언트 및 실제 봇 핸들러 **4 passed**. 전체 Python **723 passed, 69 skipped, 1 failed**이며 실패는 기존 `test_opencode_cli_help_smoke`의 외부 npx/OpenCode 실행이다. 별도 재현에서 npm 로그의 `opencode-ai@1.19.3 postinstall` 종료 코드 1을 확인했으며 더 구체적인 원인은 미확정이다. 원본은 `.artifacts/pytest-eve-full.txt`다. Eve 전체는 **344 passed, 13 skipped, 0 failed**(`.artifacts/npm-eve-full.txt`). Syncthing `.venv` launcher가 실행되지 않아 기존 DP7 Python으로 동일한 pytest를 실행했고 TEMP/TMP·캐시는 저장소 `.artifacts`로 지정했다. 실제 Discord 전송·상시 작업 등록·Postgres·재부팅은 실행하지 않았다. Jev 외부 검토 checkout은 없어 diff·구문·회귀시험으로 검토했다.

- 실행 고리: `src/all_tomorrow/overseer/{__main__,metacog,environment,loop,reports,runtime,schedule,workspace}.py`
- 기존 부품 연결: `src/all_tomorrow/researcher/materialize.py`, `storage/semantic_store.py`, `storage/postgres.py`, `adapters/workers.py`, `mcp_server.py`, `usage.py`, `web.py` (앞의 `src/all_tomorrow/` 아래)
- 실행·설정: `scripts/dp7-up.ps1`, `config/projects.local.json`(로컬 설정), `config/key-pool.example.env`, `deploy/docker-compose.yaml`
- 시험: `tests/test_overseer_loop.py`, `tests/test_overseer_loop_postgres.py`, `tests/test_overseer_usage.py`, `tests/test_decision_materialize.py`
- 문서: `README.md`, `docs/{dp7-loop,overseer-plan,roadmap,usage-panel}.md`, `docs/roadmap/stage-01-researcher/{index,02-researcher-loop,03-evaluation-self-improvement,04-runtime-and-tools,05-report-and-priority,06-acceptance}.md`, 해당 `06-acceptance/STAGE1-CLOSE-STATUS.md`, Stage 2·3 `index.md`

기존부터 미추적 상태였던 나머지 overseer 파일·시험과 `docs/overseer-role.md`는 보존했다. 커밋은 만들지 않았다.

## 2026-10-21 Windows Selector 루프 수정

상태: **개발완료**(루프 호환성 수정). Stage 1 전체는 개발중이다.

변경 파일: src/all_tomorrow/async_runtime.py, overseer/runtime.py, overseer/__main__.py, overseer/loop.py, web.py와 tests/test_async_runtime.py. Windows만 명시적 Selector loop_factory를 쓰며 전역 policy는 변경하지 않는다. 웹은 Server.serve()로 자체 루프 생성을 피하며 단일·이중 리스너에 모두 적용한다. 다른 OS의 기존 실행 방식은 유지한다. executor의 작업자 호출은 subprocess 지원을 위해 별도 스레드 Proactor로 옮긴다. DB store는 해당 스레드에 넘기지 않는다. collect --no-metacog는 DB를 사용하지 않는다.

시험: DP7 Python 3.14.6으로 관련 **26 passed**, 전체 **728 passed, 69 skipped, 1 failed**. 전체 실패는 기존 test_workers.py::TestRealCliSmoke::test_opencode_cli_help_smoke의 외부 npx 실행(returncode 1)이다. 테스트를 제거하거나 skip하지 않았다. 전체 실행 후 작업자 회귀시험을 실제 자식 Python 실행 검증으로 강화해 관련 26건을 다시 통과했다. 결과: .artifacts/pytest-loopfix-full.txt, .artifacts/pytest-loopfix-focused.txt.

지정된 .venv/Scripts/python.exe -m pytest -q는 프로세스 생성 자체가 실패했다(Unable to create process using). 기존 Syncthing venv launcher 문제 기록에 따라 실행 가능한 ~/.all-tomorrow/dp7-runtime/Scripts/python.exe로 대체했다. 기존 venv 설정은 변경하지 않았다. TEMP/TMP 및 pytest cache는 .artifacts를 사용했다.

실제 검증: key-pool.env를 비밀값 출력 없이 읽어 Windows Selector 루프에서 PostgreSQL SELECT 1 성공. 같은 DP7 Python으로 임시 API를 127.0.0.1:57700에서 띄워 lifespan DB 연결·마이그레이션 후 /healthz HTTP 200을 확인했다. 임시 프로세스는 finally에서 종료했다. 5476 예약 작업은 건드리지 않았으므로 기존 프로세스에 수정이 적용됐는지는 확인하지 않았다. 재시작 후 새 진입점이 적용된다.

변경 diff와 회귀시험으로 검토했다. Jev 외부 검토 checkout은 없어 실행하지 않았다. git diff --check 통과. 커밋하지 않았다. 전체·Stage 1·Runtime packet 상태 기록을 함께 갱신했다.
