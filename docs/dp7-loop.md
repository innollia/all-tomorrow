# DP7 자기개선 고리

## 2026-10-22 메타인지 판단 모델 전환

판단 전환 코드·회귀시험은 **개발완료**. 기존 AntigravityWorker와 WinGet 포함 discover_executable을 재사용하며 plan 모드·무인 실행, 기본 모델을 사용한다. `ALL_TOMORROW_METACOG_REASONER=antigravity|codex`(기본 antigravity), `ALL_TOMORROW_METACOG_MODEL`(Antigravity 모델 지정)을 지원한다. 실행·JSON 파싱 실패 시 그 깨어남에서만 Codex로 대체하고 SQLite·wake_applied Event·일지에 판단자/모델/대체 사유를 남긴다. 실패 예외의 프롬프트·비밀값은 기록하지 않는다. 가역적 변경의 가설 시험을 만드는 한국어 프롬프트로 보완했으며 작업자 순서와 Codex diff 심사는 유지했다.

관련 시험 **24 passed**. 실제 작은 JSON 요청은 reasoner 진입점에서 **CLI not found**로 종료되어 Gemini 응답은 미확인이다. Stage 1 전체는 개발중이다. 기본 pytest 임시 폴더 접근 거부 때문에 `--basetemp=C:/Users/fixme/.all-tomorrow/gemini-judge-full-1 -o cache_dir=C:/Users/fixme/.all-tomorrow/gemini-judge-cache`로 실행하며 전체 결과는 `C:/Users/fixme/.all-tomorrow/gemini-judge-pytest.txt`에 둔다. 외부 Jev checkout은 없어 diff·회귀시험으로 검토했다. 커밋하지 않았다.

전체 결과: **768 passed / 69 skipped / 1 failed**. 실패는 변경하지 않은 `test_workers.py::TestRealCliSmoke::test_opencode_cli_help_smoke`의 외부 npx 실행(returncode 1)이다. `npm_config_cache=C:/Users/fixme/.all-tomorrow/gemini-judge-npm-cache`로 해당 시험을 재실행해도 npm **ECOMPROMISED**로 실패했다. 전체 통과는 확인하지 못했다. 최종 Windows Proactor 명시 수정 뒤 관련 24개 시험을 다시 통과했고 `git diff --check`도 통과했다.

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

(2026-10-26 폐기) 예전에는 PC가 5분 이상 미사용이고 Codex 잔량이 확인되면 초기화까지 남은 시간/잔량에 맞춰 간격을 정했다(최소 1분, 최대 30분). 지금은 위 "메타인지 자기 고리 수정"의 최소 간격·하루 상한을 쓰고 잔량은 판단자 건너뛰기에만 쓴다. 미사용 시간은 [Windows 사용자 세션의 LastInputTime](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/ns-wtsapi32-wtsinfow)을 읽는다. WTS가 이 값을 제공하지 않는 로컬 세션은 로그인 때 뜨는 activity 작업이 입력 시각을 파일로 전달한다. 관측할 수 없으면 보류한다. 실제 사용량 소진 효율은 상시 운영 뒤 조정해야 한다.

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

- API 재시작(`schtasks /End` 직후 `/Run`, watchdog 재시작): `runtime api`는 이전 프로세스가 `api.lock`과 5476 포트를 놓을 때까지 각각 최대 30초 기다린 뒤 뜬다. 예전에는 잠금이 남아 있으면 바로 rc=1로 끝났다.

## 2026-10-26 메타인지 자기 고리 수정

10/24~10/26 사흘 동안 562번 깨어나(Codex 440·Antigravity 130·Claude 1) 대부분 "변화 없음"을 쓰는 데 모델을 썼고, [수정 판단] 39개가 거의 전부 자기 자신(중복 Goal/Work, 스냅샷 JSON, fallback 보고, 반복 호출 억제)에 대한 것이었다. 바뀐 동작:

- **변화 없으면 모델을 부르지 않는다.** 새 근거는 세션 변경·새 카드·작업 결과 이벤트(`metacog.applied/rolled_back/held/scope_changed`)·디스코드 답장(`discord.question_reply`, 보고 답장)·방향 파일 변경뿐이다. 열린 PENDING/RUNNING Work, overseer.log 경고, 직전 판단이 만든 Goal/Work/보고 이벤트는 근거가 아니다(이것들 때문에 한 번도 건너뛰지 않았다). 건너뛸 때는 `metacog_wakes`에 `skipped`와 이유를 남기고 overseer.log에 `메타인지 건너뜀(모델 호출 없음)`을 쓴다. 노션은 모델을 부를 때만 읽는다.
- **간격.** Codex 잔량 소진형 간격(`wake_delay`, 60~1800초)을 없앴다. overseer는 PC 미사용(기본 5분) 동안 10분마다 코드로만 확인하고, 모델 호출(성공·실패)은 최소 30분 간격·24시간 24회까지다. 설정: `ALL_TOMORROW_METACOG_MIN_INTERVAL_MINUTES`(30), `ALL_TOMORROW_METACOG_DAILY_LIMIT`(24), `ALL_TOMORROW_METACOG_IDLE_SECONDS`(300, 0이면 PC 사용 여부 무시), `ALL_TOMORROW_METACOG_CHECK_MINUTES`(10). key-pool.env에 넣으면 다음 루프부터 적용된다. 깨우지 않는 이유(PC 사용 중·일시정지 등)는 바뀔 때마다 `메타인지 확인 조건:`으로 남긴다. `metacog --force`는 변화·간격·상한을 무시한다.
- **방향 파일.** `~/.all-tomorrow/overseer/direction-notes.md`(관제가 사용자와 정한 방향)와 `direction.md`(사용자 원문)는 메타인지가 읽기만 한다. 메모 재작성은 `metacog-notes.md`만 바꾼다. 10/25 "AI 게임개발 프로그램" 방향을 이 파일에 복원했다. 관제 브리핑 1절에도 함께 보인다.
- **판단 대상.** 스냅샷에 `user_direction`·`control_brief`(최대 14000자)를 넣고, 프롬프트는 사용자 목표·마감 → 사용자 프로젝트 운영 문제 → (새 실패가 있을 때만) All Tomorrow 자체 순으로 보게 했다. 지난 깨어남은 3개만 보이고, 작업자 시도 진단(`attempts`, `metacog.execution_attempt`)은 스냅샷에서 뺐다. 중앙 상태는 전체 Goal/Work 목록 대신 열린 Work·최근 닫힌 10개·상태별 개수와 결과·보고·질문·답장·생성 이벤트만 담는다(예전에는 닫힌 자기 Work 목록이 스냅샷의 1/3을 차지해 사용자 세션 26개 중 25개가 잘렸다). 새 카드 30개·신탁 질문 15개까지, 스냅샷 한도는 140000자(예전 90000).
- **자기 Work 제한(코드 강제).** 같은 목적(프로젝트 + 공백·문장부호·대소문자를 뺀 제목)의 열린(PENDING·RUNNING·WAITING) Work가 있으면 만들지 않는다. All Tomorrow 자체(`all-tomorrow` 또는 이 저장소 경로)를 고치는 열린 Work가 있으면 새 자기 Work는 `metacog.self_work_deferred` 이벤트만 남긴다(디스코드 보고 없음). 같은 제목의 보고·질문은 24시간 안에 다시 보내지 않는다. 쌓인 자기 Work는 `loop.close_self_work(store, registry, reason=..., apply=True)`로 Run/Work/Goal을 CANCELLED로 닫는다(삭제 없음, `metacog.cancelled` 이벤트에 이유).
- **판단자 순서와 쿼터.** 기본 순서는 Codex → Antigravity → Claude Sonnet → Claude Haiku(`ALL_TOMORROW_METACOG_REASONER=antigravity`면 Antigravity 먼저). 쿼터 소진 문구("quota", "usage limit", "Resets in 150h28m49s" 등)는 초기화 시각만 `~/.all-tomorrow/overseer/worker-cooldowns.json`에 기억하고 그때까지 그 판단자·작업자를 부르지 않는다(시각을 모르면 1시간). 사용량 스냅샷에서 Codex 창이 소진됐으면 호출 전에 건너뛴다. 모두 대기 중이면 모델 호출 없이 `skipped`. 실행기 `run_worker`도 같은 파일을 보고 `QUOTA_COOLDOWN`으로 건너뛴다.
- **스냅샷 JSON.** 파일은 처음부터 유효한 UTF-8 JSON이었다(같은 파일을 Node.js·`-Encoding UTF8`로는 읽었다). PowerShell 5.1 `Get-Content`가 BOM 없는 UTF-8을 시스템 코드페이지(cp949)로 읽어 한글이 깨지면서 3400~4100번째 문자 근처에서 구문 오류가 났다. 프롬프트에 읽는 법(`Get-Content -Raw -Encoding UTF8`)과 Python 절대 경로(PATH에 `python` 없음)를 적었다. 별개로 직렬화한 JSON 문자열에 비밀값 가리기를 하면 `KEY=값\"`의 역슬래시가 함께 지워져 JSON이 깨질 수 있어, 문자열마다 가린 뒤 직렬화하고 쓰기 전에 다시 파싱한다. 모델 답도 파싱한 뒤 가린다.
- **10/26 12:17 이후 멈춤.** 마지막 깨어남은 12:16(완료 12:17:39). 이후 `wake_delay`가 None을 돌려줬지만 이유를 로그에 남기지 않아 직접 증거는 없다. 남은 증거: 직전 깨어남 간격이 4~5분으로 줄어 있었고(잔량 소진형), Codex 5시간·주간 창이 16:19에 새로 시작했다(세션 로그의 resets_at 기준). 가장 그럴듯한 설명은 메타인지 자신이 Codex 창을 다 써 "Codex 잔량 없음"(또는 초기화 뒤 "재수집 필요")으로 대기하다가, 창이 다시 열린 뒤(~17:00~20:11)에는 사용자가 PC를 써서 "PC 사용 중"으로 대기했고, 20:11에 일시정지 파일이 생긴 것이다. 같은 날 실행기는 10:14에 시작한 Codex 작업자가 18:28 재시작까지 끝나지 않았다. 이제 간격은 잔량에 의존하지 않고 대기 이유가 로그에 남는다.

- **자기 수정은 새 실패가 있을 때만(코드 강제).** 지난 깨어남 뒤 `metacog.rolled_back`·`metacog.held` 이벤트나 overseer.log ERROR가 없으면 All Tomorrow 자체 fix 행동은 저장 전에 빼고 관찰(mid)로만 남긴다. 강제 실행 검증(21:53, Codex)에서 프롬프트만으로는 모델이 지난 Work 생성 이벤트를 보고 다시 "중복 등록 방지" 수정을 내놓았기 때문이다. 같은 실행은 플레시핏(10/31 마감) 활동이 스냅샷에 없다는 사용자 일 관찰도 냈다.

정리한 중복 자기 Work 19건(WAITING 14·RUNNING 1·PENDING 4)의 목록은 `~/.all-tomorrow/overseer/self-work-cleanup-2026-10-26.md`에 있다. 남은 메타인지 열린 Work는 TINProject Blender 조사(WAITING) 1건이다. 자기 고리 내용으로 채워졌던 `metacog-notes.md`는 `metacog-notes.md.bak-20261026-self-loop`로 보관하고 비웠다.

## 메타인지 일시정지

`~/.all-tomorrow/overseer/metacog.paused` 파일이 있으면 overseer는 메타인지를 깨우지 않고 executor는 대기 Work를 실행하지 않는다. 사용량 수집과 보고 전송은 계속한다. 파일을 지우면 다음 1분 주기부터 다시 돈다. 2026-10-26 사용자 지시로 멈췄다(사흘 562회 깨어남, 자기 자신에 대한 중복 Work 고리, 관제가 적은 방향 메모 덮어쓰기).

## 2026-10-27 서버 목록 전체 감시와 부팅 보고

10/25 재부팅에서 Tailscale 트레이 앱이 안 떠 NoState에 머물고, 손으로 켠 인용된 사랑 작업판이 꺼진 채였다. `AllTomorrow-DP7-api-watchdog`(부팅·로그온·매분, S4U)이 API만 보던 것을 서버 목록 전체로 넓혔다. 예약 작업 트리거는 그대로이고, 코드는 `src/all_tomorrow/overseer/server_watch.py`.

- **목록.** `config/infrastructure.json`의 서비스에 `autostart`(`boot`|`logon`|`manual`)와 `start`(`task`: 예약 작업 이름 / `command`: argv + `cwd`, `{python}`은 감시가 쓰는 DP7 Python / `program`: 프로그램 경로)가 생겼다. `health.kind`에 `tailscale`(`tailscale status --json`의 BackendState=Running)과 `docker`(`docker info` 응답)가 추가됐고 콘솔 servers 화면도 같이 쓴다. 새 항목: 인용된 사랑 작업판(포트 8765, http `127.0.0.1:8765/`, `boot`), Tailscale(`logon`), Docker Desktop(`manual`, 관찰만). 시작 명령에는 비밀값을 적지 않는다.
- **점검.** 감시는 매분 돌지만 서버 점검은 4분(=실제 5분 안팎) 간격이다. `boot`/`logon` 서버가 `failed`면 `start` 방법으로 켠다. 확인 불가(`unknown`)는 건드리지 않고, `logon` 서버(Tailscale)는 로그온 세션(explorer.exe)이 없으면 기다린다. API와 감시 자신은 기존 `api_watchdog.check_once`(3분 연속 실패 + 1시간 3회 재기동 한도)가 맡는다.
- **3번 실패하면 멈춘다.** 같은 서버를 3번 켰는데 다음 점검에서도 죽어 있으면 재시도를 멈추고 `reports.enqueue`로 보고 1건을 남긴다(Eve 디스코드 봇이 전송). 서버가 다시 살아나면 상태가 지워진다. 상태 `~/.all-tomorrow/overseer/server-watch.json`, 기록 `server-watch.jsonl`.
- **Tailscale.** 로그인 방식(unattended 아님)을 유지한다. 트레이 앱은 로그온 세션에서만 뜨므로 S4U인 감시가 직접 띄우지 않고 예약 작업 `AllTomorrow-DP7-tailscale-ipn`(Interactive, 로그온 때도 실행, `tailscale-ipn.exe`)을 시작한다. 이 작업은 `scripts/dp7-up.ps1` 끝에서 등록한다. serve 설정(443→5476, 8443→8765)은 Tailscale 쪽에 남아 있어 건드리지 않는다.
- **부팅 보고.** 부팅(또는 감시가 3분 넘게 안 돌았다 다시 돈 때 = 꺼졌다 켜진 때, 빠른 시작 포함) 10분 뒤 한 번 `~/.all-tomorrow/overseer/boot-report.md`를 쓴다: 서버별 살아남/죽음/확인 불가와 이유, 자동 시작 시도 횟수. 첫 줄 요약(`요약: 살아남 N / 죽음 M (이름)`)은 관제 브리핑 5절에 한 줄로 들어가고, 자동 시작 서버가 죽어 있으면 보고 1건(`boot-report-<부팅시각>`)을 낸다. `manual` 서버(Docker 등)는 파일에만 적는다.
- **프로세스 위치.** `command`/`program` 시작은 감시 예약 작업 안에서 떼어 낸 프로세스로 뜬다. Claude 데스크톱 앱 셸에서 직접 띄운 서버는 AppData 가상화를 받으므로 감시 작업(`schtasks /Run`)이 켜게 한다.
- **임시 시작 바로가기.** 시작 폴더의 `Tailscale.lnk`, `QuoteVnDesk.lnk`는 감시가 대신하게 되어 `C:\projects\_quarantine`로 옮겼다(삭제 아님). 되돌리려면 다시 시작 폴더로 복사한다.

### 재부팅 시험 방법 (사용자 확인 후 실제 재부팅)

1. 재부팅 후 로그온하고 10분 안에 `Get-ScheduledTask AllTomorrow-DP7-* | Get-ScheduledTaskInfo`로 작업들이 돌고 있는지, `tailscale status`가 Running인지 본다(트레이 앱이 로그온 직후 떠야 한다).
2. 5~10분 뒤 `http://127.0.0.1:8765/`가 200인지, `server-watch.jsonl`에 `start_requested`/`start_launched`가 남았는지 본다.
3. 부팅 10분 뒤 `~/.all-tomorrow/overseer/boot-report.md`가 생기고, 죽은 서버가 있으면 디스코드에 보고가 오는지 본다. 빠른 시작 때문에 uptime이 안 줄어도 감시 공백(3분 이상)으로 재부팅을 알아챈다.
4. 시작 폴더 바로가기가 없는 상태에서 위가 모두 되면 성공이다.
