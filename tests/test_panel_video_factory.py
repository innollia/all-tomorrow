import json
import os

from all_tomorrow.project_panels import plugins, video_factory

PREFLIGHT = """# 사전 검사 ep-a

- 표본 512장, 10프레임 간격, 92초
- 결함 2건 작은 글자 2
- 주의 3건 읽기 시간 부족 3

## 결함

| 시각 | 종류 | 내용 | 대본 줄 |
| :--- | :--- | :--- | :--- |
"""

REPORT = """# 검수 보고서 ep-a

## 판정

- 통과: 하드컷 분당 7~20회, 11.6회
- 실패: 음량과 무음, -17.1 LUFS
- 통과: 빈 무대 0, 0개

## 측정

- 길이 72.4초
- 통과: 이 줄은 판정 구역 밖이다
"""

NOTES = """# 검수 기록

## 1차
- 고친 것: 겹침, 잘림.
- 남은 것: 음량 -16.1 LUFS로 기준 하한보다 0.1 작음.
- [ ] 은하뇌 잘림 확인
- [x] 카메라 밀기 수정
- 남은 의도적 선택
  - 밈 원본 숫자는 그대로 둔다.
"""


def _write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _project(tmp_path):
    a = tmp_path / "videos" / "ep-a"
    _write(a / "brief.md", "# 출혈 추상화 단계\n\n- 각도: 대본 본문은 패널에 나오지 않는다\n")
    for name in ("facts.md", "script.md", "shots.md", "timeline.json", "youtube.md"):
        _write(a / name, "본문")
    _write(a / "output" / "ep-a.mp4", "mp4")
    _write(a / "review" / "preflight.md", PREFLIGHT)
    _write(a / "review" / "report.md", REPORT)
    _write(a / "review" / "notes.md", NOTES)
    _write(a / "board" / "status.json", json.dumps({"a1": "승인", "a2": "수정", "a3": "승인", "a4": "계획"}))
    b = tmp_path / "videos" / "ep-b"
    _write(b / "brief.md", "주제 메모\n제목: 머리카락 한 가닥\n")
    _write(b / "script.md")
    _write(b / "timeline.json")
    _write(b / "review" / "report.md", "# 검수 보고서 ep-b\n\n- 길이 46.0초\n")
    _write(b / "output" / "history" / "old.mp4")  # an older render is not the final file
    (tmp_path / "videos" / "ep-c").mkdir()
    _write(tmp_path / ".env", "API_KEY=secret-value")
    old = _write(tmp_path / "out" / "ep-a-review.mp4", "v")
    new = _write(tmp_path / "out" / "ep-b-review.mp4", "v")
    _write(tmp_path / "out" / "ep-b-preview.mp4", "v")
    log = _write(tmp_path / "out" / "render-review.log", "렌더: out/ep-b-review.mp4")
    os.utime(old, (1_760_000_000, 1_760_000_000))
    os.utime(new, (1_760_000_600, 1_760_000_600))
    os.utime(log, (1_760_000_660, 1_760_000_660))
    return tmp_path


def test_episode_stage_qa_board_and_review_render(tmp_path) -> None:
    panel = video_factory.collect(_project(tmp_path))
    eps = {e["id"]: e for e in panel["episodes"]}
    assert set(eps) == {"ep-a", "ep-b", "ep-c"}

    a = eps["ep-a"]
    assert (a["title"], a["stage"], a["stage_index"], a["stage_total"]) == ("출혈 추상화 단계", "youtube", 8, 8)
    assert a["final"] and a["final_at"] and a["skipped"] == []
    assert a["qa"] == {"defects": 2, "warnings": 3, "verdict_pass": 2, "verdict_fail": 1,
                       "unchecked": 1, "remaining": 1, "open": 5}
    assert a["board"] == {"ok": 2, "fix": 1, "other": 1}

    b = eps["ep-b"]
    assert (b["title"], b["stage"], b["stage_index"]) == ("머리카락 한 가닥", "review", 6)
    assert b["skipped"] == ["facts", "shots"] and not b["final"] and b["final_at"] is None
    assert b["qa"]["defects"] is None and b["qa"]["verdict_fail"] is None and b["qa"]["open"] == 0
    assert b["board"] is None

    c = eps["ep-c"]
    assert c["stage"] is None and c["stage_index"] == 0 and c["qa"] is None and c["title"] is None

    assert panel["board"] == {"ok": 2, "fix": 1, "other": 1}
    render = panel["review_render"]
    assert render["video"] == "ep-b-review.mp4"
    assert render["video_at"].startswith("2025-10-09T09:03:20") and render["log_at"].startswith("2025-10-09T09:04:20")

    encoded = json.dumps(panel, ensure_ascii=False)
    for private in ("secret-value", "본문", "음량", "은하뇌"):
        assert private not in encoded


def test_missing_folders_degrade_and_plugin_is_registered(tmp_path) -> None:
    assert video_factory.collect(tmp_path) == {
        "episodes": [], "more": 0, "board": {"ok": 0, "fix": 0, "other": 0},
        "review_render": {"video": None, "video_at": None, "log_at": None}}
    assert plugins()["video-factory"] is video_factory


def test_broken_board_status_is_flagged(tmp_path) -> None:
    _write(tmp_path / "videos" / "ep" / "board" / "status.json", "{not json")
    assert video_factory.collect(tmp_path)["episodes"][0]["board"] == {"ok": 0, "fix": 0, "other": 0, "invalid": 1}
