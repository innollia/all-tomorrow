# 프로젝트 노하우 재사용 (knowhow)

README 원문 목적: "매 프로젝트마다 노하우가 쌓이고 새로운 프로젝트를 중앙에 요청하면 알아서 노하우를 선별해서 프로젝트 기반에 넣고 시작". 구현은 `src/all_tomorrow/overseer/knowhow.py`.

프로젝트별·공통 md를 만들던 `build`와 그 주기 갱신 제안은 철회했다: 신탁(`oracle_ask`)이 같은 카드를 필요할 때 바로 찾아 주므로 중복이다. 남은 것은 새 프로젝트 시드뿐이다.

## 명령

```powershell
python -m all_tomorrow.overseer knowhow [--dir <overseer 폴더>] seed <프로젝트 경로> [--kind godot-game] [--tag docker] [--limit 25] [--no-jev]
```

- `seed`: 신탁 카드 DB를 직접 본다. 이 PC `overseer.sqlite`(`store.default_dir()`, `ALL_TOMORROW_OVERSEER_DIR`로 변경)와 `peers/*.sqlite`를 읽기 전용으로 열어, `cards_fts`(trigram FTS5)에 종류(`--kind`, 생략하면 `project.godot`·`package.json`·`pyproject.toml`로 추정)의 검색어·스택 태그와 `--tag`를 OR로 질의한다. `cards_fts`가 없는 DB는 건너뛴다. 해결된 카드(해결책 20자 이상)만 남기고, 비슷한 교훈은 합치며(출처 카드 ID 보존), 태그 일치 + bm25 관련도로 순위를 매긴다. 다른 엔진의 교훈과 이 프로젝트 자신의 교훈은 뺀다. 프로젝트 이름은 카드의 cwd를 등록 프로젝트(`config/projects.local.json`)와 대조해 정한다.
- Jev 키가 있으면 후보마다 "이 프로젝트에 적용되나" choice 질문을 요청 하나로 묶어 보내 "해당 없음" 0.7 이상을 거른다. 호출 실패나 키 없음이면 규칙 결과만 쓴다.
- 결과는 `<프로젝트>/docs/knowhow.md`. 이미 그 파일이 있고 우리가 만든 것이 아니면 `docs/knowhow-seed.md`로 따로 쓰고, `AGENTS.md`(없으면 `CLAUDE.md`, 둘 다 없으면 새 `AGENTS.md`)에 링크 한 줄만 덧붙인다. 기존 파일은 덮지 않는다. 쓰는 모든 글은 `redact`를 거친다. 맞는 카드가 없으면 파일을 쓰지 않고 `{"lessons": 0, "skipped": ...}`만 돌려준다.
- `mcp_server.register_project`: 레지스트리에 없던 새 프로젝트 ID를 등록하면 자동으로 seed한다(`seed_knowhow=False`로 끄기, `kind=`로 종류 지정). 실패해도 등록은 막지 않고 결과의 `knowhow`에 사유만 남긴다.

모델·네트워크를 쓰는 것은 Jev 거르기뿐이다. 예전 build가 만든 `.artifacts/knowhow/`(git 무시)는 더 이상 읽지 않는다.
