import json
import os

import pytest

from all_tomorrow.project_panels import money, plugins

CSV = """작업ID,작업명,상태,전달문서,보고서,사용자전달,실제지원,실제판매,현금수령검증,다음행동
01,근거리근로 기준선,회수검토완료_부분완료,일 보내기/01.md,보고서/01_근거리근로.md,완료,2,0,1,04에서 근로 문의 카드 통합
02,재택AI 계정확인 전환,회수검토완료_부분완료,일 보내기/02.md,보고서/02_재택AI작업.md,완료,1,3,0,기존 계정 유무부터 확인
05,재택계정 첫유급작업 전환,계정상태입력대기,일 보내기/05.md,보고서/05_재택계정.md,미확인,미확인,미확인,,가입 진행 플랫폼명과 상태 회수
"""

README = """# 부업 조사

본문 설명은 패널에 나오지 않는다.

기준일: 2026-10-18, Asia/Seoul. 아직 서브에이전트 전달·실행·지원·판매·입금이 완료되었다고 기록하지 않는다.
"""


def _project(tmp_path, encoding):
    (tmp_path / "진행현황.csv").write_bytes(CSV.encode(encoding))
    (tmp_path / "README.md").write_text(README, encoding="utf-8")
    reports = tmp_path / "보고서"
    reports.mkdir()
    for i, name in enumerate(("01_근거리근로.md", "07_로블록스_공모전_인계.md", "05_재택계정.md")):
        report = reports / name
        report.write_text("보고서 본문 비밀", encoding="utf-8")
        os.utime(report, (1_760_000_000 + i * 60, 1_760_000_000 + i * 60))
    docs = tmp_path / "문서"
    docs.mkdir()
    for name in ("실행기준_v1.2.md", "실행기준_v1.10.md", "실행기준_v1.9.md", "실행기준_초안.md", "04_회수검토.md"):
        (docs / name).write_text("기준 본문", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-8", "cp949"])
def test_collect_reads_tasks_totals_and_document_metadata(tmp_path, encoding) -> None:
    panel = money.collect(_project(tmp_path, encoding))

    tasks = panel["progress"]["tasks"]
    assert [t["id"] for t in tasks] == ["01", "02", "05"]
    assert tasks[2] == {"id": "05", "name": "재택계정 첫유급작업 전환", "status": "계정상태입력대기",
                        "next": "가입 진행 플랫폼명과 상태 회수"}
    assert panel["progress"]["totals"] == {
        "applied": {"sum": 3, "unknown": 1}, "sold": {"sum": 3, "unknown": 1}, "cash_verified": {"sum": 1, "unknown": 0}}
    assert panel["base_date"] == "2026-10-18, Asia/Seoul"
    assert panel["report"]["name"] == "05_재택계정.md" and panel["report"]["count"] == 3
    assert panel["report"]["at"].startswith("2025-10-09T08:55:20")
    assert (panel["standard"]["version"], panel["standard"]["name"], panel["standard"]["count"]) == (
        "v1.10", "실행기준_v1.10.md", 3)

    encoded = json.dumps(panel, ensure_ascii=False)
    for private in ("본문", "비밀", "서브에이전트", "일 보내기"):
        assert private not in encoded


def test_missing_files_degrade_and_plugin_is_registered(tmp_path) -> None:
    assert money.collect(tmp_path) == {"progress": None, "base_date": None, "report": None, "standard": None}
    assert plugins()["money"] is money
