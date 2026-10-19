import json
import subprocess

from all_tomorrow.project_panels import innollia_site as site


def _site(tmp_path):
    content = tmp_path / "content"
    for rel in ("_index.md", "posts/_index.md", "posts/a.md", "posts/dan_1/index.md", "hide/x.md",
                "hide/placeholder/1.md", "hide/placeholder/2.md", "secret/s.md", "secret/notes.txt"):
        file = content / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("---\ntitle: t\n---\nbody\n", encoding="utf-8")
    chronicle = tmp_path / "static" / "chronicle"
    chronicle.mkdir(parents=True)
    (chronicle / "data.json").write_text(json.dumps({
        "v": 1, "gen": "2026-09-27T03:24", "gate": {"air": 100000, "rank": "PRIVATE RANK"},
        "topics": ["PRIVATE TOPIC"],
        "stats": {"n": 739, "sealed": 52, "src": {"a": 1}, "chars": 561491, "first": "2020-06-12T08:44",
                  "last": "2026-09-26T18:29", "imgs": 160},
        "heat": {"2026-09-26": 1},
        "entries": [{"id": "1", "t": "PRIVATE TITLE", "b": "PRIVATE BODY", "bd": "PRIVATE"}],
    }), encoding="utf-8")
    return tmp_path


def test_content_counts_per_section_without_section_lists(tmp_path) -> None:
    counts = site.content_counts(_site(tmp_path) / "content")
    assert counts == {"sections": {"hide": 3, "posts": 2, "secret": 1}, "total": 6, "truncated": False}
    assert site.content_counts(tmp_path / "nope") is None


def test_chronicle_exposes_only_gen_and_stats(tmp_path) -> None:
    info = site.chronicle_stats(_site(tmp_path) / "static" / "chronicle" / "data.json")
    assert {k: info[k] for k in ("gen", *site.STAT_KEYS)} == {
        "gen": "2026-09-27T03:24", "n": 739, "sealed": 52, "first": "2020-06-12T08:44",
        "last": "2026-09-26T18:29", "imgs": 160, "chars": 561491}
    assert set(info) == {"bytes", "mtime", "gen", *site.STAT_KEYS}
    assert "PRIVATE" not in json.dumps(info, ensure_ascii=False)


def test_chronicle_degrades_on_bad_or_missing_file(tmp_path) -> None:
    file = tmp_path / "data.json"
    assert site.chronicle_stats(file) is None
    file.write_text("{oops", encoding="utf-8")
    assert site.chronicle_stats(file)["error"] == "unparseable"
    file.write_text("[1, 2]", encoding="utf-8")
    assert site.chronicle_stats(file)["error"] == "unexpected shape"


def test_warning_only_when_chronicle_is_tracked_in_the_local_index(tmp_path) -> None:
    root = _site(tmp_path)
    no_repo = site.collect(root)
    assert no_repo["chronicle_tracked"] is None and no_repo["warnings"] == []

    subprocess.run(["git", "init", "-q", str(root)], check=True)
    untracked = site.collect(root)
    assert untracked["chronicle_tracked"] is False and untracked["warnings"] == []

    subprocess.run(["git", "-C", str(root), "add", site.CHRONICLE], check=True)
    tracked = site.collect(root)
    assert tracked["chronicle_tracked"] is True and tracked["warnings"] == [site.TRACKED_WARNING]
    assert tracked["chronicle"]["n"] == 739 and tracked["content"]["total"] == 6
    assert "PRIVATE" not in json.dumps(tracked, ensure_ascii=False)


def test_collect_on_an_empty_folder(tmp_path) -> None:
    panel = site.collect(tmp_path)
    assert panel["content"] is None and panel["chronicle"] is None and panel["warnings"] == []
