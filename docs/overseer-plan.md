# 교차 세션 관제 계획서

### 2026-10-23 중앙 API 무응답 감시

- **개발완료**(코드·회귀시험): API와 독립된 1분 S4U 작업에서 새 연결로 `/healthz`를 3초 타임아웃 검사한다. 3회 연속 실패하면 연결 상태별 수·리스너 PID·핸들 수·스레드 상태를 기록하고 API 예약 작업만 종료/정지 확인/시작한다. 재시작 시도(명령 실패 포함)를 영속 저장하고 최근 1시간 3회를 넘기려 하면 자동 복구를 중단하고 `reports.enqueue`에 `[보고] 중앙 API …`를 적재한다. `api.log`와 `api-watchdog.jsonl`에 시도·결과를 남기며 실제 회복은 다음 health 검사로 판정한다.
- 원인 구분: **확정**은 Uvicorn 기본 로깅이 stderr/stdout 전용·propagate=false여서 runtime의 `api.log`에 연결되지 않았다는 점이다(설치 Uvicorn 0.54.0 설정·별도 프로세스 파일 기록 시험으로 확인). `log_config=None, access_log=False`로 root 파일 로그에 연결하고, HTTP 4xx/5xx·처리 예외만 URL/헤더/본문/예외 메시지 없이 기록한다. asyncio accept 오류도 같은 파일에 남는다. **장애 원인은 미확정**이다. CPython 3.14.6의 `_accept_connection`은 자원 부족 시 reader를 제거하고 지연 재등록하며, 다른 OSError는 루프 오류 처리기로 전달한다. 해당 경로가 당시 실패했다는 증거는 없다. Windows 513 소켓 `select()`의 `ValueError: too many file descriptors in select()`는 재현했지만 루프 유휴 증상과의 인과·누수는 증명하지 못했다([Python 공식 제약](https://docs.python.org/3.13/library/asyncio-platforms.html)). 따라서 루프 구현은 바꾸지 않았다.
- 운영 관측: 현재 5476 health는 정상. 기존 api.log 32줄에서 accept 오류/Uvicorn 기동 로그는 없었다. 이 세션의 `Get-NetTCPConnection`은 `PermissionDenied / HRESULT 0x80041003`이라 운영 연결·스레드 진단은 미확인이다. 진단 명령의 UTF-8을 명시하고, 권한/시간 초과 등 진단 실패는 오류 종류만 기록한 뒤 재시작한다.
- 관제 배포: 관리자 PowerShell에서 `scripts/dp7-up.ps1` 재실행으로 `AllTomorrow-DP7-api-watchdog`를 새로 등록한다(사용자 TaskPrefix도 지원). 기존 API 프로세스는 별도로 `Stop-ScheduledTask -TaskName AllTomorrow-DP7-api` 후 `Start-ScheduledTask -TaskName AllTomorrow-DP7-api`로 재시작해야 새 로그 설정이 적용된다. 등록 스크립트의 Start만으로 실행 중 API가 교체되지는 않는다. 실작업에서 분당 실행·정지/시작 권한·장애 복구·진단 파일을 확인한다. 자동 복구 중단은 시간이 지나도 유지하며, 수동 점검·복구 후 overseer 디렉터리의 `api-watchdog.json`을 제거하면 해제된다. 기본 Eve 전송은 중앙 API가 살아야 적재된 보고를 가져갈 수 있으므로, API가 계속 멈춘 동안에는 Discord 즉시 전달을 보장하지 않는다. 커밋·운영 작업 등록/재시작은 수행하지 않았다.
- 검증: 관련 **44 passed**, 최종 전체 **802 passed / 69 skipped / 1 failed**(80.21초). 실패는 기존 `tests/test_workers.py::TestRealCliSmoke::test_opencode_cli_help_smoke`의 외부 npx 실행(returncode=1)이며, 쓰기 가능한 npm 캐시를 지정한 별도 실행도 실패했다. 지정 DP7 Python에 `--basetemp`·`-o cache_dir`만 추가해 기존 tmp/cache 접근 제한을 피했으며 시험 제외·skip 변경은 없다. 원본 결과는 `.artifacts/api-watch-full-final.txt`, 관련 결과는 `.artifacts/api-watch-related.txt`에 있다. 실제 PowerShell 등록 스크립트는 가짜 scheduler cmdlet으로 실행해 6개 작업과 watchdog의 S4U/분당/IgnoreNew/60초 실행 제한을 확인했다. PowerShell 구문·diff 공백 검사 통과. Jev 실행기 미설치로 diff·회귀시험을 직접 검토했다.
- 변경 파일: `src/all_tomorrow/overseer/api_watchdog.py`, `src/all_tomorrow/api_logging.py`, `src/all_tomorrow/overseer/runtime.py`, `src/all_tomorrow/web.py`, `scripts/dp7-up.ps1`, `tests/test_api_watchdog.py`, `tests/test_overseer_hands.py`, 이 문서, `docs/roadmap.md`, `docs/roadmap/stage-01-researcher/index.md`, `docs/roadmap/stage-01-researcher/04-runtime-and-tools.md`. 시작 전에 있던 Syncthing 관련 변경은 보존했다.

### 2026-10-22 메타인지 Antigravity 판단 전환

- **개발완료**(코드·회귀시험): 기본 Antigravity plan 판단, 환경변수 선택·모델 지정, 깨어남별 Codex 대체와 SQLite/Event/일지 기록, 가역적 가설 시험 프롬프트를 연결했다. 작업자·diff 심사는 기존 Codex 순서를 유지한다. 관련 24 passed. 실제 호출은 agy CLI 미발견으로 Gemini 응답 미확인. 전체 시험과 설정은 [DP7 기록](dp7-loop.md)에 남긴다.
- 전체 **768 passed / 69 skipped / 1 failed**: 기존 OpenCode help smoke가 npx/npm ECOMPROMISED로 실패했다. 시험은 변경하지 않았고 전체 통과는 미확인이다.

### 2026-10-21 Work 실행·헛도는 깨어남 수정

상태: **개발중**(관제 재등록·실제 Work 성공 검증 대기). 강제 깨어남과 자기 wake_applied 이벤트 재관측을 막고, 작업자별 실패·시간 초과·시험/반영 단계 진단을 Event·executor.log·복구 기록·보고에 연결했다. 예외·무변경 성공 뒤 fallback, WinGet agy 탐색, Interactive/Limited 등록·1분 재기동, 한국어 프롬프트를 보완했다. 관련 64 passed, 전체 747 passed / 69 skipped / 기존 OpenCode smoke 1 failed. 실제 Codex 재현은 sandbox 홈 오류이며 운영 두 Work의 앞 CLI 원인은 미확정이다. 확인/추론 구분과 관제 명령은 [DP7 진행 기록](dp7-loop.md#2026-10-21-work-실패무변경-깨어남-보정)을 따른다.

- 상태: **개발중**. 모으기·정리·신탁과 메타인지 판단→Work→작업자→시험→반영/되돌림→보고 적재를 연결했다. 실제 DP7 DB·Discord·재부팅 운영은 확인 전이다. 현재 실행 방법은 [DP7 자기개선 고리](dp7-loop.md), 과거 기록은 아래 진행 기록을 본다.
- README 목표와의 연결:
  - 목표 4 "프로젝트 노하우 재사용"
  - 목표 5 "작업 계층과 병렬인 메타인지 계층"
  - 지금까지 이 둘은 테스트된 부품(`researcher/`, `knowledge.py`)만 있다. 실제로 돌아가는 루프는 없다.

## 1. 완료된 상태

- **사용자는 지금처럼 일한다.** Claude Code, Codex, OpenCode, Kiro, Antigravity의 각 세션에 직접 일을 시킨다.
  - 관제는 요청을 받는 창구가 아니다.
  - 모든 일을 보고하는 창구도 아니다.
- **관제는 기록을 정리해 둔다.** 모든 세션의 기록을 모아, 값싼 모델로 `문제 → 시도 → 해결` 카드로 정리한다.
  - 카드에는 에이전트, 모델, 프로젝트, 상황 태그가 붙는다.
  - 정리는 세션이 끝난 뒤 한 번씩 한다. 실시간으로 지켜보지 않는다.
- **막힌 세션이 관제에 묻는다.** 같은 문제로 헛돌기 전에 세션이 신탁 버튼 `oracle_ask(문제)`를 부른다.
  - 관제는 다른 프로젝트나 세션의 해결 카드를 찾아 답한다. 없으면 "없음"이라고 짧게 답한다.
  - 관제가 세션을 계속 지켜보는 방식은 쓰지 않는다. 모델 토큰을 계속 쓰는 데 비해 얻는 게 적다(2026-10-20 사용자 판단).
- **세션이 잊고 안 물을 때를 위한 안전장치.** 같은 오류가 반복되면 AI 없이 카드 검색만 해서 맞는 게 있을 때 세션에 붙여 준다.
  - 이 안전장치는 Claude Code 훅부터 지원한다.
- **관제는 자기 답도 본다.** 준 답이 실제로 쓰였는지는 그 세션의 다음 정리에서 판정한다. 안 쓰이거나 틀린 답이 나온 유형은 검색 기준을 고친다.
  - 별도의 메타-메타 계층은 두지 않는다. 같은 정리기가 관제의 기록도 재료로 삼는다(ADR 0003).

| 필수 | 선택 (나중) |
|---|---|
| 다섯 도구의 기록을 증분으로 모은다 | 중앙 서버 미러(폰에서 카드 보기) |
| 외부 모델로 보내기 전에 비밀값을 가린다 | 벡터 검색 |
| 카드에 근거(원본 세션·메시지 범위)가 남는다 | 에이전트·모델별 해결률 화면 |
| 다섯 도구 모두에서 신탁 버튼(`oracle_ask`)을 부를 수 있다 | 새 프로젝트 시작 시 카드 묶음 자동 주입 |
| 질문과 답, 그 답이 쓰였는지를 기록한다 | 다른 도구의 반복 오류 안전장치 |

## 2. 재료 (2026-10-20 이 PC에서 측정)

| 도구 | 위치 | 형식 | 양 |
|---|---|---|---|
| Claude Code | `~/.claude/projects/*/*.jsonl` | JSONL | 287MB, 최상위 세션 31개(서브에이전트 포함 파일 143개) |
| Codex | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` | JSONL | 1.7GB, 139개. codex-control MCP로 스레드 목록·내용 읽기 확인 |
| OpenCode | `~/.local/share/opencode/opencode.db` | SQLite. `session`에 agent·model·토큰·비용, `message`·`part`에 내용 | 40GB, 세션 512, 메시지 33,675, part 139,629 |
| Antigravity | `~/.gemini/antigravity/conversations/*.db`, `conversation_summaries.db`(FTS), `brain/` | SQLite | 대화 282 |
| Kiro | `~/.kiro/sessions/cli/*.jsonl` | JSONL | 1개 |

- 원본의 대부분은 도구 출력(파일 내용, 로그)이다.
- 정리에 필요한 건 사용자 메시지, 에이전트의 최종 답, 오류 앞뒤 몇 줄뿐이다. 수집기가 결정적으로 걸러 episode당 수 KB로 줄인다.
- OpenCode DB 40GB는 그 자체로 이상 징후다. 원인은 이 계획과 별개로 확인한다.

## 3. 구조

```text
[수집기]  LLM 없음, 도구별 어댑터, 증분 커서, 비밀값 가림
    ↓ episode (세션이 끝난 뒤)
[정리기]  무료 모델. episode → 카드(문제·시도·해결·결과·태그·근거)
    ↓ 카드 (SQLite FTS5 + 태그)
[질문 창구]  MCP oracle_ask(문제) — 신탁 버튼, 다섯 도구에 등록
    ├─ 세션이 막히면 직접 부름
    └─ 안전장치: Claude Code 훅이 반복 오류를 보면 AI 없이 카드 검색
    ↓ 질문·답 기록
[정리기]  다음 정리에서 그 답이 쓰였는지 판정 → 검색 기준 조정
```

- 실행 위치는 이 PC다. 기록·프로젝트 폴더·git이 모두 여기 있다.
  - 수집기와 정리기는 device agent처럼 Windows 예약 작업으로 띄운다(pythonw, 파일 로그).
  - AWS는 쓰지 않는다. 중앙 서버 미러는 선택 사항이다.
- 저장 위치는 `~/.all-tomorrow/overseer/`(저장소 밖)다. 대화 내용을 담기 때문이다.
- 재사용할 것:
  - 카드 승격 기준: `knowledge.py`(근거 2개 이상이어야 accepted)
  - 무료 모델 라우팅: 아이디어 공장의 LiteLLM 라우터 설정(키 회전, 쿨다운)
  - MCP 서버: `mcp_server.py`. 2026-10-20 Claude 세션에서 연결 타임아웃이 났으므로 먼저 고친다.

### 카드

| 필드 | 내용 |
|---|---|
| agent / model | claude-code·codex·opencode·kiro·antigravity / 실제 모델명 |
| project | 세션 작업 폴더 기준 |
| situation | OS, 셸, 언어, 도구, 오류 종류 태그 |
| problem / attempts / solution | 증상, 실패한 시도, 효과가 있던 해결 |
| outcome | 해결 / 미해결 / 포기 |
| evidence | 원본 도구, 세션 id, 메시지 범위, 날짜 |
| status | candidate → accepted(독립 근거 2개 이상) → retired |

## 4. 질문 창구

다섯 도구 모두 MCP를 지원하므로, 세션에 메시지를 밀어 넣는 도구별 방법을 따로 찾지 않는다. 같은 MCP 도구 하나를 각 도구에 등록한다.

| 도구 | 등록 위치 | 지침 위치 | 확인 상태 |
|---|---|---|---|
| Claude Code | 사용자 범위 MCP(이미 등록, 타임아웃) | `~/.claude/CLAUDE.md` | 연결 수리 필요 |
| Codex | `~/.codex/config.toml` | `~/.codex/AGENTS.md` | 미확인 |
| OpenCode | `opencode.json` mcp | 전역 AGENTS.md | 미확인 |
| Kiro | `~/.kiro` 설정 | steering 파일 | 미확인 |
| Antigravity | `~/.gemini/antigravity/mcp` | 전역 규칙 | 미확인 |

### 언제 묻는가 (각 도구 지침에 넣을 내용)

- 같은 문제로 두 번 실패하면, 세 번째 시도 전에 `oracle_ask`를 부른다.
- 처음 보는 도구·환경 오류를 만나면 먼저 부른다.
- 관제의 답은 참고 정보다. 근거 세션을 보고 지금 상황에 맞는지 판단해서 쓴다.

### 답하는 방식

- 카드 검색(AI 없음)으로 후보를 찾는다. 후보가 있을 때만 값싼 모델이 지금 문제에 맞는지 고르고 짧게 요약한다.
- 답 형식: 한 줄 요지, 해결 요약, 근거(도구·프로젝트·날짜).
- 맞는 카드가 없으면 "없음"이라고 바로 답한다. 관제가 대신 문제를 풀지 않는다.

## 5. 보안

- 기록에는 사용자가 붙여 넣은 키가 들어 있다(예: 2026-10-19 All Tomorrow 세션).
  - 무료 모델 제공자는 입력을 로깅하거나 학습에 쓸 수 있다.
  - 사용자는 개인정보가 학습에 쓰이는 것은 허용했다. 하지만 키 노출은 별개 문제다.
- 외부로 보내기 전에 다음을 가린다.
  - `key-pool.env`의 모든 값(정확 일치)
  - 저장소들의 `.env` 값
  - 일반 키 패턴: `sk-`, `AIza`, `ghp_`, `AKIA`, `xox`, `Bearer` 등
- 테스트: key-pool 값이 하나라도 외부 요청 본문에 나오면 실패한다.

## 6. 비용과 부하

- 백필은 최신 세션부터, 무료 할당량 안에서 며칠에 걸쳐 한다. 그 뒤의 증분은 작다.
- 실시간 감시가 없으므로, 모델 호출은 정리할 때와 질문을 받았을 때만 일어난다.
- OpenCode DB는 읽기 전용으로 열고, `time_updated` 기준으로 증분한다.

## 7. 단계

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| 1 모으기 | 다섯 도구 어댑터, 증분 커서, 가림, episode 저장. LLM과 외부 전송 없음 | 소스별 세션 수가 원본과 일치. 가림 테스트 통과 |
| 2 정리 시범 | 에이전트별로 섞은 세션 10개 → 카드 | 사용자가 카드를 보고 쓸 만하다고 판정. 아니면 모델·프롬프트·episode 자르기를 바꿈 |
| 3 질문 창구 | 신탁 MCP `oracle_ask`, 카드 검색, 과거 기록 정리 시작 | 과거에 해결된 문제로 물으면 해당 카드가 답으로 나옴 |
| 4 다섯 도구 연결 | 각 도구에 MCP 등록과 지침 추가, Claude Code 반복 오류 훅 | 다섯 도구 각각에서 실제로 불러 답을 받음 |
| 5 자기 관찰 | 질문·답 기록, 답이 쓰였는지 판정 | 쓰이지 않은 답의 유형이 검색 기준 변경으로 실제로 줄어듦 |

## 8. 미확인

- 무료 모델이 지저분한 기록에서 쓸 만한 카드를 뽑는지는 2단계 시범으로 판정한다.
- 각 도구의 MCP 등록 방법과 지침 파일 위치(§4).
- 모델이 지침대로 실제로 묻는지는 4단계 이후 질문 기록으로 확인한다. 안 물으면 안전장치를 넓힌다.
- OpenCode DB 40GB의 원인.
- 다른 기기(노트북 등) 세션의 기록은 범위 밖이다.

## 진행 기록 (2026-10-20)

### 1단계 모으기: 완료

- 코드: `src/all_tomorrow/overseer/`(`sources.py`, `redact.py`, `store.py`), 실행 `python -m all_tomorrow.overseer collect`.
- 저장: `~/.all-tomorrow/overseer/overseer.sqlite`, 로그 `overseer.log`.
- 결과: 원본 약 44GB → 23MB. 다시 모으기는 바뀐 세션만 읽어 약 3초.

| 도구 | 모은 세션 | 독립 확인 | 서브에이전트 |
|---|---|---|---|
| Claude Code | 143 | 파일 143(최상위 31 + subagents 112) | 112 |
| Codex | 139 | 파일 139 | 0 |
| OpenCode | 528 | `session` 512 + `session_v2`에만 있는 16 | 457 |
| Kiro | 267 | `.json` 267 | 267(전부 subagent로 기록됨) |
| Antigravity | 278 | 요약 DB 278. 대화 DB는 282개라 4개는 검색 색인이 없어 못 읽음 | 130 |

- 가림: 비밀값 45개 + 키 모양 패턴. 실제 저장본에서 486곳이 가려졌고, 알려진 비밀값·키 모양이 남은 세션은 0개다.
- 첫 수집에서 Kiro 2개가 실패했다. 도구 결과가 객체가 아니라 문자열인 형식이 있었고, 고친 뒤 다시 모았다.
- Kiro와 Antigravity 기록에는 도구 실패 표시가 없어 `[E]` 줄이 0개다. Antigravity는 단계 기록이 protobuf라, 로컬 검색 색인의 사용자·에이전트 본문만 읽는다.
- OpenCode DB가 40GB인 원인: 대화에 붙인 이미지가 `part` 행에 data URL로 통째 들어 있다(수집기는 이 행을 건너뜀). 정리는 이 계획 밖의 일이다.

### 2단계 정리 시범 / 3단계 신탁 버튼: 구현, 판정 대기

- 정리: `distill.py`. 로컬 LiteLLM gateway(아이디어 공장 것, `127.0.0.1:4000`)로 무료 모델 그룹을 차례로 쓴다. 보내기 직전에 다시 가리고, 알려진 비밀값이 남아 있으면 보내지 않는다.
- 신탁: `oracle.py`(카드 전문 검색, trigram FTS, 모델 호출 없음, 질문 기록), `oracle_mcp.py`(도구 하나 `oracle_ask`).
  - 프로젝트에 작업을 지시하는 기존 `all_tomorrow.mcp_server`와 분리했다. 다른 도구들에는 이 읽기 전용 서버만 붙인다.
- 테스트: `tests/test_overseer_*.py` 11개 통과.
- 기존 `all_tomorrow.mcp_server`가 2026-10-20 이 세션 시작 때 30초 타임아웃이 났었다. 다시 띄우면 약 5초(import 3.9초)에 정상 응답해서 원인은 확인하지 못했다.

### 2단계 시범 결과 (2026-10-20 13:03)

- 세션 10개(도구별 2개), 무료 모델 `nemotron-3-super-120b:free` → 카드 35개, 실패한 덩어리 0개, 약 10분.
- 쓸 만한 카드 예: OpenRouter 402(잔여 크레딧보다 큰 max_tokens), 402/403 공급자 24시간 격리, 잘린 JSON 복구, 크롬 실행 중 쿠키 파일 WinError 32, 설치 직후 gh PATH, 폴더 이동 시 Device busy, Python 없을 때 PowerShell System.Drawing으로 이미지 처리, OpenCode `Model not found`.
- 문제: 프로젝트에서만 의미 있는 카드(판매 수치 착시, DB 경로)가 섞임. 같은 내용 카드가 중복됨(Python 없음 4장). 한 카드는 max_tokens를 올렸다고 하고 다른 카드는 내렸다고 해서 서로 어긋남.
- 신탁 실검색: "OpenRouter 402" → 위 카드 3장, "Device or resource busy" → 1장, "셰이더 컴파일 실패" → 없음.
- 사용자 판정 전이다.

### 4단계 다섯 도구 연결 (2026-10-20 14:40)

사용자 결정: 신탁 버튼은 각 에이전트가 직접 쓴다. 관제 Claude 세션은 질문에 답하지 않고, 메모 정리와 답이 쓰였는지 보는 메타인지만 맡는다(관제가 묻는 쪽의 코드를 다시 읽으면 같은 모델이 같은 코드를 두 번 읽게 되므로).

| 도구 | 서버 등록 | 사용 지침 | 실제 호출 확인 |
|---|---|---|---|
| Claude Code | `~/.claude.json` `mcpServers.oracle` | `~/.claude/CLAUDE.md` | 미확인. 새로 여는 세션부터 로드됨 |
| Codex | `~/.codex/config.toml` `[mcp_servers.oracle]`, 읽기 전용이라 `default_tools_approval_mode = "approve"` | `~/.codex/AGENTS.md` | `codex exec`로 호출 → wobnovel 카드 반환 |
| OpenCode | `~/.config/opencode/opencode.jsonc` `mcp.oracle` | `~/.config/opencode/AGENTS.md` | `opencode run`으로 호출 → wobnovel |
| Kiro | `kiro-cli mcp add --scope global` | `~/.kiro/steering/oracle.md` | `mcp list`에 보임. 호출은 Kiro 계정이 AWS에 의해 일시 정지되어 시험 못 함 |
| Antigravity | `~/.gemini/config/mcp_config.json` | `~/.gemini/GEMINI.md` | 신탁 질문 기록에 antigravity 호출이 남음 |

- 편집한 파일은 모두 `<파일>.bak-oracle-<시각>`으로 백업했다.
- 처음 만든 fastmcp 서버는 import가 약 2.5초라, Codex가 도구 목록을 정한 뒤에야 떠서 도구가 보이지 않았다. MCP JSON-RPC를 직접 처리하는 가벼운 서버로 바꿔 import 0.3초가 됐고, 그 뒤 Codex에서 보였다.
- 자동 실행: Windows 예약 작업 `AllTomorrowOverseer`, 1시간마다 `pythonw -m all_tomorrow.overseer run`(새 기록 모으기 → 아직 정리 안 된 세션 20개 정리). 최근 30분 안에 갱신된 세션은 작업 중으로 보고 건너뛴다. 모델 gateway(`127.0.0.1:4000`)가 꺼져 있으면 정리는 건너뛰고 모으기만 한다. gateway는 아직 자동 시작되지 않는다.
- 남은 일: 관제 Claude 세션(메모 중복 합치기, 어긋난 메모 표시, 프로젝트 전용 메모 걸러내기, 신탁 답이 쓰였는지 판정).

### 방향 수정 (2026-10-20 15:30)

- 사용자 지적: 신탁 효과 판정 명령(`oracle-review`/`oracle-verdict`)과 브리핑의 신탁 통계는 원래 목표에서 어긋난다. 자기개선 절차를 코드로 박아 둔 것이고, README가 금지한 "추상적 하드코딩"이다.
- 걷어냈다: `oracle_reviews` 테이블, 판정·통계 코드, `card-status` 명령.
- 관제 = 모든 걸 보고 만지는 Claude 세션 하나. 사용자도 개별 세션에 직접 일을 시킨다. 메타인지(신탁을 계속 쓸지 포함)는 관제가 원본 기록을 읽고 스스로 판단한다.
- 관제 지침: `docs/overseer-role.md`. 볼 수 있는 것, 할 수 있는 것, 기억 파일만 적고 절차는 적지 않았다.
- 남긴 것: 수집(다섯 형식 44GB를 한곳에서 읽게 함), 가림, 정리 카드, 신탁 버튼, 브리핑(입력 모음일 뿐, 판단 없음).

### 메타인지 루프, 거친 첫 버전 (2026-10-20 16:00)

- 사용자 지적: "부를 때만 일하는 관제 세션"은 설계한 메타인지가 아니다. README·ADR 0003의 메타인지는 작업 계층과 나란히 스스로 관찰하고, 아무도 말하지 않은 문제를 찾고, 작업과 자기 자신을 바꾸는 계층이다. 관제 세션 지침(`overseer-role.md`)과 시작 카드는 버렸다.
- 사용자 결정: 1시간마다 도는 예약 작업으로 거칠게 구현한다.
- 구현: `src/all_tomorrow/overseer/metacog.py`. 예약 작업 `run` = 모으기 → 정리 → 메타인지 한 번 깨우기. 따로 실행은 `python -m all_tomorrow.overseer metacog [--force]`.
  1. 지난 깨어남 이후 바뀐 것으로 스냅샷을 만든다.
     - 다섯 도구의 바뀐 세션(끝 30줄), 새 카드, 신탁 질문
     - 이 시스템 자신의 오류 로그
     - 프로젝트 git, 노션 프로필
     - 자기 지난 깨어남 8번과 자기 메모
  2. Codex(무인, 읽기 전용)에게 원래 목표와 함께 넘긴다. 점검 목록은 주지 않는다. Codex는 필요하면 파일을 직접 열어 조사한다.
  3. 돌아온 관찰과 행동(report/propose)은 `metacog_wakes` 테이블과 `~/.all-tomorrow/overseer/metacog-journal.md`에 남긴다. 메모(`metacog-notes.md`)는 메타인지가 매번 스스로 고쳐 쓴다. 자기 판단 기준을 스스로 바꾸는 부분이다.
- 바뀐 게 없으면 모델을 부르지 않는다. 메타인지 자신의 Codex 실행은 `--ephemeral`이고 스냅샷에서도 뺀다.
- 거친 부분(남은 일)
  - 프로젝트를 직접 바꾸지 못한다. 바꿀 것은 제안으로만 남는다.
  - 일반 자기개선의 자동 적용(평가 후 승격)이 없다.
  - 보고가 PC의 일지 파일에만 있다. 폰에서 볼 곳과 알림이 없다.
  - Codex 구독 사용량을 매시간 쓴다.
- 첫 실제 깨어남(2026-10-20 18:55): 관찰 3개와 제안 1개가 나왔다.
  - 스스로 찾은 것: 스냅샷이 글자 수로 잘려 JSON이 깨져 있었다. 이건 내 구현 버그였고, 세션 단위로 덜어내도록 고쳤다.
  - 그 밖의 관찰: TINProject로 기록된 세션이 실제로는 GuineaStar를 작업한 경우가 있다.
  - 메타인지가 쓴 메모: "깨어남 한 번을 주기적 자율 운영 완료로 간주하지 않는다", "같은 설계를 재조사하지 말고 후속 변화만 확인한다".
- 이 과정에서 고친 것: 정리기가 모델 응답을 기다리는 내내 DB 쓰기 잠금을 쥐고 있어 메타인지가 "database is locked"로 실패했다. 모델 호출을 먼저 끝내고 한 번에 쓰도록 바꿨다.

### 두 PC 운영 (2026-10-20 23:10)

- 사용자 결정: aaaa(노트북)는 모으기·정리만 하고, 메타인지는 DP7-desktop에서만 돈다. 두 PC 기록은 DP7에서 합쳐 본다.
- 예약 작업: aaaa는 `run --no-metacog`, DP7은 `run`.
  - 각 PC는 run이 끝날 때 자기 DB의 사본을 `~/.all-tomorrow/peers/<호스트>.sqlite`로 올린다(`store.publish`).
  - Syncthing 폴더 `all-tomorrow-secrets`는 `~/.all-tomorrow`에서 `key-pool.env`와 `peers/*.sqlite`만 공유한다.
- 메타인지 스냅샷과 신탁 검색은 다른 PC의 사본도 읽기 전용으로 함께 본다.
  - 확인 결과(DP7, 23:09): 스냅샷에 host가 aaaa와 DP7 두 개로 나온다.
- DP7 쪽 차이
  - gateway venv는 `%LOCALAPPDATA%\all-tomorrow\gateway-venv`(동기화 안 함)에 있다.
  - `.stignore-shared`에 `gateway-venv`를 넣었다. DP7의 core `.stignore`는 공용 파일을 include하지 않아서 그쪽에 직접 넣었다.
- aaaa의 `C:\projects\_sync\battery-guard.ps1`은 배터리일 때 Syncthing 전체를 멈춘다(사용자 규칙, 유지). 그동안에는 DP7의 메타인지가 aaaa의 새 기록을 받지 못한다.
- 미해결
  - `claude-config` 폴더에서 `projects\C--projects-wobnovel` 삭제가 충돌한다(원격에서 지웠는데 aaaa에 무시된 파일이 남아 있음).
  - 예약 작업 실행 시 gateway를 자동으로 켜는 동작은 아직 실제 재부팅 뒤에 확인하지 않았다.
- 변경(2026-10-20 23:20, 사용자): aaaa의 모으기·정리·사본 올리기는 하지 않는다. aaaa 예약 작업은 Disabled. 메타인지는 Codex 사용량을 아끼려고 6시간에 한 번만 깨어난다(`ALL_TOMORROW_METACOG_EVERY_HOURS`, 기본 6). DP7의 모으기·정리는 그대로 매시간 돈다.
- 변경(2026-10-20 23:12, 사용자: "이 PC에서 하는 게 안 올라가면 안 된다"): aaaa 예약 작업을 다시 켰다. 이제 `run --collect-only`로 모으기와 사본 올리기만 한다. 모델 호출은 없고 1초 미만이다. 원본 기록을 그대로 동기화하지 않는 이유는 OpenCode DB만 40GB이기 때문이다. aaaa 세션의 카드는 새로 생기지 않는다(DP7의 정리는 자기 DB만 다룸).
- 변경(2026-10-20 23:15, 사용자: "오픈코드는 버려"): OpenCode를 수집 대상에서 뺐다(`Roots.listings`, 어댑터 코드는 남김). aaaa 저장소의 opencode 세션 529개와 카드 5개를 지웠다. DP7에도 같은 정리를 요청했다. 사용자는 "요약은 사용량이 든다"고 생각했지만, 모으기(요약본 만들기)는 모델을 쓰지 않는다고 설명했다. 사용량이 드는 것은 DP7의 정리(무료 모델)와 메타인지(Codex)뿐이다.

### DP7 자기개선 고리 연결 (2026-10-21)

- Syncthing 감시 전체 시험(2026-10-23): **787 passed / 69 skipped / 1 failed**, 기존 `test_opencode_cli_help_smoke`의 외부 npx 실행 실패다. 기본 임시/캐시 폴더 접근 거부 때문에 지정 DP7 Python에 쓰기 가능한 `--basetemp`·`cache_dir`를 사용했다. npm 캐시를 작업 폴더로 옮겨도 외부 smoke 실패가 남았으며 시험 제거·skip 변경은 없다. 원본은 `.artifacts/sync-watch-pytest-final.log`, 최종 관련 시험은 20 passed다. 프로세스/포트 실운영 확인과 Discord 실제 수신은 남았다.

- 2026-10-23 Syncthing 자동 감시: **개발완료**(코드·회귀시험). `python -m all_tomorrow.overseer sync-health`와 `run --no-metacog`/`run --collect-only`의 수집 직전 점검을 연결했다. 설정 키 ping, 부모 트리, Syncthing 소유 TCP 포트, 원격 연결·lastSeen 및 2시간 초과/Tailscale 응답을 관측한다. 키/연결 거부·중복·포트 누락만 재기동하며 같은 원인은 1시간 간격, 로컬 날짜 하루 3회로 제한한다. 조회 권한 오류는 고장으로 단정하거나 재시작하지 않는다. JSON·SQLite에 결과와 최근 7일 이상 이력을 보존하고 peers 사본을 DP7이 읽어 기존 reports.enqueue로 날짜/호스트/원인별 한 번 보고한다. 동기화가 끊긴 동안 노트북 새 결과는 DP7에 도착할 수 없으며 재연결 뒤 전달된다. 설정·.stignore·다른 홈 데이터는 수정하지 않았다. 00:41 실제 DP7 API pong, AAAA-laptop connected=true, lastSeen=2026-10-23T00:41:05+09:00. 최초 구현의 PowerShell 비종료 오류를 빈 프로세스 목록으로 오인해 복구 1회 시도·실패 기록이 생겼다. CIM 접근 거부를 명시적 점검 불가로 처리하도록 수정하고 재시도 방지 시험을 추가했다. 최종 프로세스 트리/포트 소유 검증은 sandbox 권한 제한으로 미확인이다. 관련 20 passed, 전체 결과는 아래 기록을 따른다. Jev 설치/키가 없어 diff·시험으로 검토했으며 커밋하지 않았다.

- 2026-10-22 로그인 오보·답장 보정: **개발완료**(코드·회귀시험). Claude 갱신·사용량 요청에 명시적 User-Agent를 넣고 실제 인증 거부와 차단·통신·파일 오류를 분리해 비밀값 없는 이유를 중앙에도 보존했다. 파일 보고를 Event로만 찾던 404 경로를 확인·수정했으며 답장을 중복 없이 원자 저장하고 다음 메타인지 스냅샷·깨움·근거 참조에 연결했다. 모르는 메시지는 200/linked=false다. 최종 관련 **33 passed**, 전체 **763 passed / 69 skipped / 1 failed**(기존 `test_opencode_cli_help_smoke`: npx 60초 timeout). 기본 tmp/cache 권한 오류로 지정 DP7 Python에 `--basetemp`·`-o cache_dir`만 추가했으며 시험 제거·skip 변경은 없다. Jev 설치가 없어 diff·회귀시험으로 검토했고 공백 검사도 통과했다. Eve 수정·커밋·운영 재시작은 하지 않았으며 실계정·Discord 운영 확인은 남았다.

- 2026-10-21 Eve 창구 연결: 기존 edge 토큰으로 보고 파일 재전송·Event 답장·LLM 선판단 후 중앙 Goal 요청을 연결하고 `scripts/dp7-eve-{up,run}.ps1`을 추가했다(미실행). 관련 Python 24 passed, Eve 연결 4 passed; 전체 Python 723 passed / 69 skipped / 기존 OpenCode CLI smoke 1 failed. 실제 Discord·Postgres·재부팅은 확인 전이며 운영 명령과 변경 파일은 [DP7 문서](dp7-loop.md)에 기록했다.

- 메타인지가 운영 문제를 판단해 기존 validate_decision → DecisionMaterializer → lineage/BudgetLedger로 Goal/Work를 만든다. 문제 키 중복·하루 생성 예산·영속 provenance는 기존 semantic store의 Event와 PostgreSQL advisory transaction으로 묶었다.
- 별도 작업 실행기가 Codex → Antigravity → 무료 gateway 순으로 사본을 수정한다. 고정 시험과 실제 diff 심사를 통과하면 커밋 없이 파일을 반영하고, 실패·중단 시 백업/manifest로 복구한다. 사용자 자료 삭제·권한/비용 확대·방향 선택·등록 폴더 밖은 실행하지 않고 질문으로 쌓는다.
- Run/Work/Goal 결과와 보고 Event를 함께 확정하고 다음 메타인지 스냅샷에 포함했다. Discord 값이 없으면 파일에 쌓고 값이 생기면 밀린 보고를 보낸다.
- 고정 6시간 대신 PC 미사용 시간과 Codex 잔량/초기화 시각으로 깨어날 때를 정한다. Codex 공식 live 사용량 RPC와 관측 시각 기반 로그 fallback, Claude 만료 토큰 갱신, 없어진 프로젝트 경로 건너뛰기를 추가했다.
- DP7 등록용 scripts/dp7-up.ps1은 만들기만 했다. API·작업 실행기·메타인지·수집·사용자 입력 관측을 부팅/로그인 때 실행할 준비다. Postgres/Discord 비밀값 이름과 관제 명령은 [운영 문서](dp7-loop.md)에 적었다.
- 최종 관련 시험: 89 passed. 전체 python -m pytest -q: 720 passed, 69 skipped, 1 failed. 기존 OpenCode 실 CLI help smoke가 이 Windows sandbox에서 바이너리를 실행하지 못했다. 기존 Antigravity smoke는 이번 PATH에서 CLI가 없어 skip됐다. 시험을 제거하거나 skip으로 바꾸지 않았다. 원본 결과: .artifacts/pytest-loop-final.txt.
- PowerShell 구문·Python 컴파일·diff 공백 검사 통과. 실제 Postgres(AT_TEST_POSTGRES_URL 미설정), Discord 전송, 실계정 사용량 갱신, 재부팅 뒤 운영은 확인 전이다. 이 sandbox의 하위 Codex는 홈 디렉터리 접근 문제로 live 조회를 확인하지 못했다.
- Stage 0 완료 기록은 유지하고, Stage 1은 개발중, Stage 2·3은 선행작업 대기로 정정했다. 부분 시험 통과를 전체 운영 완료로 표시하지 않는다. git 커밋은 하지 않았다.
