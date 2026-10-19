import json
import os
from pathlib import Path

from all_tomorrow.project_panels import plugins
from all_tomorrow.project_panels import snowday

TODO = """- 대화창 만들기 - 성공!
- 이동 시스템 구현하기 - 성공!
- 안정적인 콜라이징 시스템 구축하기 - 진행 중
- 인벤토리 구현하기 - 성공!

- 아주 극히 간단한 가비지컬렉터 만들기 - 성공!
- Z 연타 시 첫 대사창이 반복 시작되는 문제 - 진행 중
- 세이브 슬롯
"""

ESC = "\x1b"
HEAD = f"|\no  Downloading tools\n|\n{ESC}[2K{ESC}[1A{ESC}[2K{ESC}[G|\n*  Tools downloaded\n|\no  Compiling for windows\n" \
       "|  Failed to load Options from C:\\Users\\someone\\Desktop\\game\\local_settings.json\n|  Success\n"

FAILED = HEAD + "|  Saving IFF file... C:\\Users\\someone\\Desktop\\game\\out\\Snow Day.win\n" \
                "|  Converting snd_poyo to Wav 16bit mono @ 44100Hz\nx  Failed\nnode.exe : Command failed:\n" \
                "    + FullyQualifiedErrorId : NativeCommandError\n\nIgor exited with code 4294967295\n"
SUCCEEDED = HEAD + "|  Igor complete.\n*  Compilation finished\n"
STALLED = HEAD + "|  Error : Unable to write resource snd_poyo in C:\\Users\\someone\\Desktop\\x.wav\n" \
                 "|  Writing Chunk... SHDR size ... 0.00 MB\n"


def write(root: Path, rel: str, data: bytes | str, mtime: float | None = None) -> Path:
    file = root / rel
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    if mtime is not None:
        os.utime(file, (mtime, mtime))
    return file


def utf16(text: str) -> bytes:
    """PowerShell `>` redirect: UTF-16 LE with BOM, CRLF."""
    return b"\xff\xfe" + text.replace("\n", "\r\n").encode("utf-16-le")


def test_plugin_is_registered() -> None:
    assert plugins()["snowday-orig"] is snowday


def test_todo_counts(tmp_path) -> None:
    write(tmp_path, snowday.TODO_FILE, TODO)
    todo = snowday.todo_counts(tmp_path)
    assert {k: todo[k] for k in ("done", "in_progress", "todo", "other", "total")} == \
        {"done": 4, "in_progress": 2, "todo": 1, "other": 0, "total": 7}


def test_build_results_by_marker_and_encoding(tmp_path) -> None:
    failed = snowday.build_result(write(tmp_path, "notes/build_a.log", utf16(FAILED)))
    assert failed["result"] == "fail" and failed["exit_code"] == 4294967295
    assert failed["last_step"] == "Converting snd_poyo to Wav 16bit mono @ 44100Hz"
    ok = snowday.build_result(write(tmp_path, "notes/build_b.log", SUCCEEDED))
    assert ok["result"] == "success" and ok["exit_code"] is None
    stalled = snowday.build_result(write(tmp_path, "notes/build_c.log", STALLED))
    # A per-step "|  Success" is not a build result; no final marker means it never finished.
    assert stalled["result"] == "incomplete" and stalled["errors"] == 1
    assert stalled["first_error"] == "Unable to write resource snd_poyo in …"


def test_collect_picks_newest_log_and_keeps_paths_out(tmp_path) -> None:
    write(tmp_path, snowday.TODO_FILE, TODO)
    write(tmp_path, "notes/build_2024.log", utf16(FAILED), mtime=1_000_000)
    write(tmp_path, "notes/build_2025.log", SUCCEEDED, mtime=2_000_000)
    write(tmp_path, "notes/~syncthing~build_2026.log.tmp", FAILED, mtime=3_000_000)
    write(tmp_path, snowday.PREVIEW_FILE, "<html></html>")
    write(tmp_path, "디스코드대화/log.txt", "someone else's message")
    panel = snowday.collect(tmp_path)
    assert panel["latest_build"]["name"] == "build_2025.log" and panel["latest_build"]["result"] == "success"
    assert [b["name"] for b in panel["builds"]] == ["build_2025.log", "build_2024.log"]
    assert panel["latest_ambiguous"] is False
    assert panel["dialogue_preview"]["exists"] is True and panel["todo"]["total"] == 7
    encoded = json.dumps(panel, ensure_ascii=False)
    assert "someone" not in encoded and "Users" not in encoded and len(encoded.encode()) < 20_000


def test_same_mtime_logs_are_flagged_ambiguous(tmp_path) -> None:
    write(tmp_path, "notes/build_a.log", FAILED, mtime=1_000_000)
    write(tmp_path, "notes/build_b.log", SUCCEEDED, mtime=1_000_000.03)
    assert snowday.collect(tmp_path)["latest_ambiguous"] is True


def test_empty_folder_degrades_to_notes(tmp_path) -> None:
    panel = snowday.collect(tmp_path)
    assert panel["todo"] is None and panel["latest_build"] is None and panel["builds"] == []
    assert panel["dialogue_preview"] == {"exists": False, "mtime": None}
    assert panel["notes"] == [f"{snowday.TODO_FILE} 없음", "notes/build_*.log 없음"]
