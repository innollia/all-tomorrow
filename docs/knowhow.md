# 프로젝트 노하우 재사용 (knowhow)

README 원문 목적: "매 프로젝트마다 노하우가 쌓이고 새로운 프로젝트를 중앙에 요청하면 알아서 노하우를 선별해서 프로젝트 기반에 넣고 시작". 구현은 `src/all_tomorrow/overseer/knowhow.py`.

## 명령

```powershell
python -m all_tomorrow.overseer knowhow build                      # 모델 호출 없음
python -m all_tomorrow.overseer knowhow seed <프로젝트 경로> [--kind godot-game] [--tag docker] [--limit 25] [--no-jev]
```

- `build`: 이 PC `overseer.sqlite`와 `peers/*.sqlite`의 해결된 카드(cards)를 읽어 주제 태그(엔진·도구·배포·AI모델·워크플로)를 붙이고, 비슷한 교훈을 합친다(출처 카드 ID 8자리 보존). 출력은 `.artifacts/knowhow/`(git 무시): `projects/<project>.md`(프로젝트당 관찰 횟수 순 최대 60개), `common.md`(둘 이상 프로젝트에서 반복되었거나 프로젝트에 안 묶인 교훈 최대 100개), `index.json`(seed 입력). 쓰는 모든 글은 `redact`를 거친다. 프로젝트 이름은 카드의 cwd에서 등록 프로젝트(`config/projects.local.json`)와 대조해 정하고, `subagent_*`·`C:`·`workspace` 같은 폴더 이름은 공통 풀로 보낸다. 폴더는 `ALL_TOMORROW_KNOWHOW_DIR`로 바꾼다.
- `seed`: `index.json`에서 종류(`--kind`, 생략하면 `project.godot`·`package.json`·`pyproject.toml`로 추정)의 스택 태그 일치 + 인메모리 FTS(bm25) 관련도로 후보를 고르고, 다른 엔진의 교훈은 뺀다. Jev 키가 있으면 후보마다 "이 프로젝트에 적용되나" choice 질문을 요청 하나로 묶어 보내 "해당 없음" 0.7 이상을 거른다. 호출 실패나 키 없음이면 규칙 결과만 쓴다. 결과는 `<프로젝트>/docs/knowhow.md`. 이미 그 파일이 있고 우리가 만든 것이 아니면 `docs/knowhow-seed.md`로 따로 쓰고, `AGENTS.md`(없으면 `CLAUDE.md`, 둘 다 없으면 새 `AGENTS.md`)에 링크 한 줄만 덧붙인다. 기존 파일은 덮지 않는다.
- `mcp_server.register_project`: 레지스트리에 없던 새 프로젝트 ID를 등록하면 자동으로 seed한다(`seed_knowhow=False`로 끄기, `kind=`로 종류 지정). `index.json`이 없거나 실패해도 등록은 막지 않고 결과의 `knowhow`에 사유만 남긴다.

## 주기 갱신 — 관제가 붙일 위치

metacog.py·schedule.py·runtime.py는 건드리지 않았다. 갱신은 모델을 안 쓰는 독립 명령이라 어디에든 붙는다.

1. 권장: `overseer/__main__.py`의 `run` 경로(예약 작업 collect)에서 `store.publish(base)` 뒤, `_refresh_control_brief(store, base)` 바로 옆에 `knowhow.build(base, knowhow.knowhow_dir())`를 try/except로 한 번 호출한다(실패해도 이전 파일 유지). `--collect-only` 경로에는 넣지 않는다.
2. 또는 별도 예약 작업이 하루 1회 `python -m all_tomorrow.overseer knowhow build`를 실행한다.

build는 카드 약 2500개에 몇 초 걸리고 모델·네트워크를 쓰지 않는다. Jev를 쓰는 것은 seed뿐이다.
