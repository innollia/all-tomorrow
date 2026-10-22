# 관제 브리핑 — 2026-10-22

상태: **개발완료**(중앙 수신·요약·브리핑 구현, 회귀시험, 실제 노션 읽기). Eve 송신 연결 후의 실제 대화 요약과 기존 API 프로세스의 새 경로 적용은 운영 확인으로 남는다. Stage 1 전체는 **개발중**이다. 커밋하지 않았다.

## 동작과 실행

`python -m all_tomorrow.overseer control-brief`가 `~/.all-tomorrow/overseer/control-brief.md`를 원자적으로 교체한다. `--dir`와 `ALL_TOMORROW_OVERSEER_DIR`도 기존처럼 지원한다. 매시간 `run --no-metacog` 및 runtime의 collect 경로에서 publish 다음에 같은 갱신을 호출한다. `--collect-only`는 기존처럼 모델 없는 수집·발행만 한다.

`POST /internal/edge/discord/messages`는 기존 edge Bearer 인증을 재사용한다. Eve 계약의 `source`, `batch_id`, 메시지 필드를 받으며 500개·2MiB를 초과하면 4xx다. `message_id`를 기본키로 중복을 제거하고 `{accepted, duplicates}`를 반환한다. 대화와 요약은 별도 `discord.sqlite`에 저장하므로 peers 사본에 포함되지 않는다. 알려진 비밀값은 저장 및 모델 전송 직전에 기존 Redactor로 가린다.

무료 모델 그룹은 기존 distill과 같고 LiteLLM을 사용한다. 서버/채널/스레드·UTC 날짜별 미처리 구간을 요약한다. 성공한 부분과 요약을 한 트랜잭션으로 기록하므로 중복 수신, 늦게 도착한 과거 메시지, 긴 메시지의 일부 실패에도 성공 구간을 다시 보내지 않는다. 실패 구간은 다음 수집 때 다시 시도한다. 모델 호출의 HTTP timeout은 45초이며 5분 예산을 구간 사이에 확인한다. 이미 진행 중인 호출은 완료까지 기다린다. 게이트웨이가 꺼졌거나 요약에 실패하면 최근 원문 발췌와 상태를 표시한다.

노션은 key-pool.env의 NOTION_TOKEN으로 읽기만 한다. 루트 00 고정 주소 목록에서 목표·프로젝트 원장과 일기 원장, 일일 기록 인덱스를 찾고, 실행 인덱스와 실행·할일 원장도 읽는다. 진행/주력 목표, 미완료 할 일, 최근 나흘 일기의 속성과 본문을 수집하며 기존 brief.load_notion 프로필도 유지한다. 이 확장 문맥은 로컬 관제 파일에만 넣는다.

브리핑 순서는 큰 방향 원문과 D-day → 노션 → 최근 72시간 디스코드 → 메타인지 일지·Work 수·최근 보고 → 기존 프로젝트별 세션 활동이다. 오래된 자료부터 생략하며 약 8,000자 이내로 조립한다. 원문 발췌·페이지 ID·메시지 ID를 남긴다. Work 집계는 read-only 조회이며 DB를 읽지 못하면 0으로 꾸미지 않고 미확인으로 쓴다.

## 변경 파일

- `src/all_tomorrow/overseer/discord_edge.py`: 인증·스트리밍 본문 한도·계약 검증·수신 경로.
- `src/all_tomorrow/overseer/discord_digest.py`: 로컬 SQLite·멱등 저장·요약 구간 추적·최근 발췌.
- `src/all_tomorrow/overseer/control_brief.py`: 노션·큰 방향·메타인지·활동 조립과 원자적 저장.
- `src/all_tomorrow/overseer/__main__.py`: 수동 명령·예약 수집 연결.
- `src/all_tomorrow/idea_factory/llm.py`: 기존 기본값 300초를 유지하며 호출별 timeout 인자 허용.
- `tests/test_control_brief.py`: 인증·중복·500개 및 2MiB 경계·요약 재시도·늦은 메시지·긴 메시지·노션 필터·원자적 저장·Work 집계·매시간 연결 시험.
- 이 문서와 `docs/roadmap.md`, `docs/roadmap/stage-01-researcher/index.md`: 범위와 실제 검증 상태.

다른 작업자가 수정 중인 metacog.py, docs/dp7-loop.md, docs/overseer-plan.md는 이 작업에서 수정하지 않았다.

## 검증 결과

지정 DP7 Python으로 관련 시험 **18 passed**. 최종 전체 시험 **781 passed / 69 skipped / 1 failed**. 실패는 기존 `TestRealCliSmoke.test_opencode_cli_help_smoke`의 외부 `npx -y opencode-ai run --help`다. 기본 npm 캐시 쓰기가 거부됐고, 쓰기 가능한 별도 캐시에서도 OpenCode 네이티브 패키지 설치/실행에 실패했다. 신탁 조회 후 진단했으며 시험을 삭제·skip하거나 CLI를 모조하지 않았다. 전체 통과를 주장하지 않는다.

기본 pytest 임시 폴더도 접근 거부되어 다음과 같이 쓰기 가능한 경로를 지정했다.

```powershell
C:/Users/fixme/.all-tomorrow/dp7-runtime/Scripts/python.exe -m pytest -q --basetemp=C:/Users/fixme/.all-tomorrow/test-control-full-2 -o cache_dir=C:/Users/fixme/.all-tomorrow/test-control-cache --tb=short --disable-warnings
```

Jev 외부 리뷰 checkout은 없어 diff·인증 경계·트랜잭션·실패 복구·시험의 결정적 검토로 대체했다. 변경 파일 `git diff --check` 통과.

실제 `control-brief` 실행은 성공했다. **6,598자**, 요청 순서의 **다섯 섹션**을 확인했다. 노션 API HTTP 200과 실제 목표·할 일·일기 본문을 확인했으며 Work는 열린 0 / 실패 2였다. 현재 디스코드 수신 메시지는 없어 그 사실을 표시한다. 브리핑에 알려진 비밀값이 남지 않은 것도 값 출력 없이 확인했다. 실제 Discord 대화에 대한 모델 요약은 아직 검증하지 않았다.
