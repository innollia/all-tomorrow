import json
from pathlib import Path

from all_tomorrow.project_panels import plugins
from all_tomorrow.project_panels import tinproject as tin

KIT_STATUS = """# IMPLEMENTATION_STATUS — Kit 05

> **2026-09-27 부모(통합 담당) 전달 — 사용자 답. 이 파일의 다른 내용보다 우선한다.** (§0.2 질문 1~4의 답)
> 1. 방향은 C로 확정.

> 이 파일이 **사실의 원천**이다.

최종 갱신: 2026-09-27
브랜치: `kit/05-stone-story-rpg`

---

## 0. 다음 세션이 먼저 읽을 것

1. 개체 표현은 반려됐다.

### 0.2 사용자 답을 기다리는 것 (2026-09-27, sub-kit05)

| # | 질문 | 후보 | 상태 |
|---|---|---|---|
| Q1 | 개체 생김새 | A / B / C | 대기. 에이전트 추천 A |
| Q2 | 플레이어도 같은 리그인가 | 이미 같은 리그 | 이미 진행 |
| Q3 | 몸 설계 | 3계열 | 이미 진행 |
| Q4 | 다리 표현 | 다리 다발 | 대기 |

### 0.1 2026-09-27 세션 작업 묶음

| 묶음 | 내용 | 상태 |
|---|---|---|
| 1 | 장면 | 대기 |

## 6. 코드를 실행하는 법

```
# 임포트 (새 class_name 등록)
godot --headless --import
```
"""

MODULE_STATUS = """# 인용된 사랑 — 현재 상태

## 지금 되는 것
- 작품 5개.

## 다음 할 일
1. 대사 쌍을 늘린다.
   - 춘향전 4쌍뿐.
2. 화자 검수를 추가한다.
3. 초상을 바꾼다.

## 질문 (답을 기다리지 않고 추천안대로 진행)
1. '마' 작품은 동백꽃.
2. 번역은 자체 번역.
"""

SCORE = """# 인용된 사랑 자동 채점


## 총점 100.0 / 100
- 1) 원문 실존 100.0
- 2) 바로 다음 대사 97.5
- 3) 규칙 단위 테스트 100.0

## 1) 원문 실존: 282 / 282
"""

EVAL = """# 일치율 평가 보고서 (eval_report)

## 요약

- 규칙서 v1 → v6로 5번 고쳤다.
- 최종(v6, 3번 돌린 평균): 통과/퇴짜 일치 97%, 이유 일치 67%.
- 처음(v1): 통과/퇴짜 일치 92%, 이유 일치 46%.

## 회차별 결과

| 회차 | 규칙서 | 판정 일치 | 이유 일치 | 고친 것 |
|---|---|---|---|---|
| 1 | v1 | 12/13 (92%) | 6/13 (46%) | 첫 판 |
| 8 | v6 | 13/13 (100%) | 9/13 (69%) | 재실행 |
"""


def write(root: Path, rel: str, text: str) -> None:
    file = root / rel
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")


def make_project(root: Path, *, godot: bool = True, sentinel: bool = True) -> Path:
    if godot:
        write(root, "project.godot", "config_version=5\n")
    write(root, ".dryforge/status.json", json.dumps({"initialized": True, "current_cycle": {
        "branch": "feat/death-and-gimmicks", "intent": "Game Over loop & Field Gimmicks"}}))
    for cycle in ("001", "002"):
        write(root, f".dryforge/{cycle}/plan.md", "x")
    write(root, "plans/kits/05_STONE_STORY_RPG_KIT/IMPLEMENTATION_STATUS.md", KIT_STATUS)
    write(root, "plans/kits/04_TOP_DOWN_ACTION_RPG_KIT/README.md", "x")
    write(root, "plans/kits/03_DEDUCTION_CASEWORK_KIT.md", "x")
    write(root, "modules/quote_vn/STATUS.md", MODULE_STATUS)
    write(root, "modules/quote_vn/reports/score.md", SCORE)
    write(root, "modules/jar_climb/main.gd", "x")
    write(root, "tools/avatar_judge/eval_report.md", EVAL)
    if sentinel:
        write(root, tin.SENTINEL, "# PRESENCE SENTINEL\n")
    return root


def test_plugin_is_registered() -> None:
    assert plugins()["tinproject"] is tin


def test_collect_reads_real_formats(tmp_path) -> None:
    panel = tin.collect(make_project(tmp_path))
    assert panel["dryforge"] == {"branch": "feat/death-and-gimmicks", "intent": "Game Over loop & Field Gimmicks",
                                 "cycles": 2, "latest_cycle": "002"}
    [kit] = panel["kits"]
    assert kit["kit"] == "05_STONE_STORY_RPG_KIT" and kit["title"] == "Kit 05"
    assert kit["updated"] == "2026-09-27" and kit["branch"] == "kit/05-stone-story-rpg"
    # Only the §0.2 table counts (not §0.1's 상태 column); 대기 rows are pending.
    assert (kit["pending_questions"], kit["questions"], kit["answer_note"]) == (2, 4, True)
    assert panel["kits_without_status"] == ["04_TOP_DOWN_ACTION_RPG_KIT"]
    mods = {m["name"]: m for m in panel["modules"]}
    assert mods["jar_climb"] == {"name": "jar_climb", "status_file": False}
    assert (mods["quote_vn"]["next"], mods["quote_vn"]["questions"]) == (3, 2)  # nested bullet not counted
    assert mods["quote_vn"]["questions_note"] == "답을 기다리지 않고 추천안대로 진행"
    assert panel["quote_score"]["total"] == 100.0 and panel["quote_score"]["max"] == 100.0
    assert [p["score"] for p in panel["quote_score"]["parts"]] == [100.0, 97.5, 100.0]
    judge = panel["judge_eval"]
    assert (judge["verdict_pct"], judge["reason_pct"], judge["basis"]) == (97.0, 67.0, "v6, 3번 돌린 평균")
    assert (judge["first_verdict_pct"], judge["first_reason_pct"]) == (92.0, 46.0)
    assert panel["sentinel"]["state"] == "present"
    assert panel["sync"]["in_progress"] is False and panel["notes"] == []
    assert len(json.dumps(panel, ensure_ascii=False).encode()) < 20_000


def test_eval_report_without_summary_falls_back_to_last_round(tmp_path) -> None:
    write(tmp_path, tin.EVAL_FILE, EVAL.replace("- 최종(v6, 3번 돌린 평균): 통과/퇴짜 일치 97%, 이유 일치 67%.\n", ""))
    judge = tin.judge_eval(tmp_path)
    assert (judge["verdict_pct"], judge["reason_pct"], judge["basis"]) == (100.0, 69.0, "마지막 회차")


def test_missing_sentinel_alarms_only_when_not_syncing(tmp_path) -> None:
    synced = tin.collect(make_project(tmp_path / "a", sentinel=False))
    assert synced["sentinel"]["state"] == "missing"
    syncing = tin.collect(make_project(tmp_path / "b", godot=False, sentinel=False))
    assert syncing["sync"]["in_progress"] and syncing["sentinel"]["state"] == "sync_hold"
    assert any("project.godot" in reason for reason in syncing["sync"]["reasons"])


def test_syncthing_temp_files_signal_sync_and_are_ignored(tmp_path) -> None:
    root = make_project(tmp_path, sentinel=False)
    write(root, "assets/art/~syncthing~ship.png.tmp", "partial")
    write(root, "modules/~syncthing~new_module.tmp", "partial")
    (root / "modules" / "~syncthing~dir").mkdir()
    panel = tin.collect(root)
    assert panel["sync"]["in_progress"] and panel["sentinel"]["state"] == "sync_hold"
    assert all(not m["name"].startswith("~syncthing~") for m in panel["modules"])


def test_scan_is_bounded(tmp_path, monkeypatch) -> None:
    for i in range(30):
        (tmp_path / f"d{i:02}").mkdir()
    write(tmp_path, "d29/deep/~syncthing~x.tmp", "partial")
    write(tmp_path, "project.godot", "x")
    monkeypatch.setattr(tin, "SYNC_SCAN_ENTRIES", 10)
    sync = tin.sync_state(tmp_path)
    assert sync["scanned_entries"] == 10 and not sync["scan_complete"] and not sync["in_progress"]


def test_empty_folder_degrades_to_notes(tmp_path) -> None:
    panel = tin.collect(tmp_path)
    assert panel["dryforge"] is None and panel["kits"] == [] and panel["modules"] == []
    assert panel["quote_score"] is None and panel["judge_eval"] is None
    assert {".dryforge 없음", "plans/kits 없음", "modules 없음"} <= set(panel["notes"])
    assert panel["sentinel"]["state"] == "sync_hold"  # no project.godot: treated as still syncing


def test_broken_status_json_is_a_note(tmp_path) -> None:
    write(tmp_path, ".dryforge/status.json", "{not json")
    notes: list[str] = []
    assert tin.dryforge(tmp_path, notes)["branch"] is None and notes == [".dryforge/status.json 해석 실패"]
