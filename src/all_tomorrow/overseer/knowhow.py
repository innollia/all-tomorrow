"""Cross-project know-how: seed a new project with lessons from the oracle's card DBs.

seed: queries ``cards_fts`` of this PC's overseer.sqlite and the peers' published stores (all
read-only) with the project kind's words and tags, keeps solved cards, merges near-duplicate lessons
(source card ids are kept), ranks them by tag match + bm25, optionally asks Jev (one request, one
question per candidate) whether each applies, and writes ``docs/knowhow.md`` into the project.
Existing files are never overwritten; AGENTS.md / CLAUDE.md only gets a link line.

Per-project / common lesson files were withdrawn: they duplicated the oracle (``oracle_ask``).
Every written text passes through the redactor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from all_tomorrow.overseer.redact import Redactor, default_secret_files
from all_tomorrow.overseer.store import default_dir, open_peer, peer_paths

REPO_ROOT = Path(__file__).resolve().parents[3]
MARKER = "<!-- all-tomorrow:knowhow-seed -->"
MIN_SOLUTION = 20
CANDIDATES = 400          # rows per card DB taken from the FTS query
SIMILAR = 0.55            # token Jaccard above which two lessons are the same lesson
JEV_DROP = 0.7            # drop a candidate when Jev says "does not apply" at least this surely

# Folder names that say nothing about a project (working directories of agent tools, drive roots).
GENERIC = {"", "c:", "projects", "workspace", "desktop", "decision", "_bg", "fixme", "game", "sy",
           "downloads", "documents", "tmp", "temp", "home", "src"}
_GENERIC_RE = re.compile(r"^(subagent_[0-9a-f]+|[a-z]+-[a-z]+-[0-9a-f]{6}|referenced-.*|create-this-.*|c-users-.*|phase-.*)$")

# topic -> tag -> regex (matched case-insensitively on problem + situation + solution)
TOPICS: dict[str, dict[str, str]] = {
    "엔진": {
        "godot": r"godot|gdscript|\.tscn|\.gd\b", "unity": r"\bunity\b|\.unity\b|monobehaviour",
        "unreal": r"unreal|\bue[45]\b", "pygame": r"pygame", "phaser": r"phaser", "renpy": r"ren'?py",
        "roblox": r"roblox|luau", "blender": r"blender|bpy\b", "web-game": r"canvas|webgl|three\.js|pixi",
    },
    "도구": {
        "git": r"\bgit\b|rebase|cherry-pick|\.gitignore|merge conflict", "powershell": r"powershell|\.ps1|pwsh",
        "python": r"python|pip\b|venv|pytest|\.py\b", "node": r"\bnode(js)?\b|npm|pnpm|typescript|\bvite\b",
        "sqlite": r"sqlite|\bfts5\b", "ffmpeg": r"ffmpeg|ffprobe", "playwright": r"playwright|puppeteer|selenium",
        "mcp": r"\bmcp\b|fastmcp", "postgres": r"postgres|psycopg|asyncpg",
        "electron": r"electron|tauri",
    },
    "배포": {
        "docker": r"docker|container", "aws": r"\baws\b|\bec2\b|\bs3\b|lightsail|cloudfront", "ssh": r"\bssh\b|scp\b|rsync",
        "systemd": r"systemd|systemctl|cron\b|schtasks|task scheduler", "nginx": r"nginx|caddy|reverse proxy",
        "github-pages": r"github pages|gh-pages", "syncthing": r"syncthing", "tailscale": r"tailscale|tailnet",
        "discord": r"discord",
    },
    "AI모델": {
        "gemini": r"gemini", "claude": r"claude|anthropic", "codex": r"codex|openai|gpt-?\d|chatgpt",
        "litellm": r"litellm|openrouter|gateway", "local-llm": r"ollama|llama\.cpp|gguf",
        "image-gen": r"comfyui|stable diffusion|sdxl|midjourney|flux|image gen|이미지 생성",
        "tts": r"\btts\b|edge-tts|voice|음성", "rate-limit": r"\b429\b|rate.?limit|quota|할당량|api key|api키",
        "agent-cli": r"opencode|antigravity|kiro|subagent|서브에이전트",
    },
    "워크플로": {
        "windows": r"windows|win32|cp949|\bcmd\b|c:\\\\|백슬래시", "encoding": r"cp949|utf-?8|unicode|인코딩|mojibake|bom\b",
        "paths": r"path|경로|symlink|junction|long path", "testing": r"pytest|unit test|테스트|\bci\b",
        "handoff": r"handoff|핸드오프|인수인계|worktree|브랜치 충돌|concurrent|동시 작업",
        "capture": r"screenshot|캡처|스크린샷|화면 녹화",
    },
}
_TOPIC_RES = {t: {tag: re.compile(rx, re.I) for tag, rx in tags.items()} for t, tags in TOPICS.items()}
TAG_TOPIC = {tag: t for t, tags in TOPICS.items() for tag in tags}
BASE_TAGS = {"windows", "powershell", "git", "encoding", "paths"}   # every project on this PC meets these

# project kind -> stack tags and words for the relevance search
KINDS: dict[str, dict] = {
    "godot-game": {"tags": ["godot", "git", "capture", "testing", "image-gen", "tts"],
                   "query": "godot gdscript scene 게임 캡처 에셋"},
    "unity-game": {"tags": ["unity", "git", "capture", "testing"], "query": "unity 게임 scene prefab"},
    "pygame": {"tags": ["pygame", "python", "capture", "testing"], "query": "pygame 게임 python"},
    "web-game": {"tags": ["web-game", "node", "playwright", "github-pages", "capture"], "query": "canvas 웹 게임 브라우저"},
    "python-service": {"tags": ["python", "testing", "sqlite", "postgres", "docker", "systemd"],
                       "query": "python pytest 서비스 데몬"},
    "web-app": {"tags": ["node", "playwright", "docker", "nginx", "aws", "github-pages"], "query": "웹 서버 프론트엔드 배포"},
    "ai-agent": {"tags": ["mcp", "claude", "codex", "gemini", "litellm", "agent-cli", "rate-limit", "handoff"],
                 "query": "에이전트 mcp 모델 api 키 서브에이전트"},
    "video-pipeline": {"tags": ["ffmpeg", "tts", "image-gen", "python"], "query": "영상 ffmpeg 음성 이미지 생성"},
}


def detect_kind(path: Path) -> str | None:
    """Best guess from the files of the project; None when nothing is recognisable."""
    names = {p.name.lower() for p in path.iterdir()} if path.is_dir() else set()
    if "project.godot" in names:
        return "godot-game"
    if "assetsunityplaceholder" in names or ("assets" in names and "projectsettings" in names):
        return "unity-game"
    if "package.json" in names:
        return "web-app"
    if "pyproject.toml" in names or "requirements.txt" in names:
        return "python-service"
    return None


# ---- reading cards -------------------------------------------------------------------------

_SOLVED = re.compile(r"^\s*(해결|resolved|solved|fixed)", re.I)
_UNSOLVED = re.compile(r"미해결|unresolved|unsolved|미완료", re.I)


def is_solved(outcome: str) -> bool:
    return bool(_SOLVED.match(outcome or "")) and not _UNSOLVED.search(outcome or "")


def known_projects() -> dict[str, str]:
    """Registered project ids (config/projects.local.json) -> folder name, lower-cased."""
    path = Path(os.environ.get("ALL_TOMORROW_PROJECTS", REPO_ROOT / "config" / "projects.local.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8")).get("projects", {})
    except (OSError, ValueError):
        return {}
    return {pid: Path(str(v.get("path", pid))).name for pid, v in data.items() if isinstance(v, dict)}


def resolve_project(project: str | None, cwd: str | None, known: set[str]) -> str:
    """Project name for a card, "" when the card is not tied to one (goes to the common pool)."""
    by_lower = {k.lower(): k for k in known}
    for cand in [project or ""] + [p for p in re.split(r"[\\/]", cwd or "") if p]:
        low = cand.lower()
        if low in by_lower:
            return by_lower[low]
        head = re.split(r"[-_]", low)[0]
        if len(head) >= 5 and head in by_lower:     # TINProject-avatar-judge -> TINProject
            return by_lower[head]
    name = (project or "").strip()
    if name.lower() in GENERIC or _GENERIC_RE.match(name.lower()):
        return ""
    return name


def _fts_query(words: list[str]) -> str:
    terms, seen = [], set()
    for w in words:
        w = w.strip().lower()
        if len(w) >= 3 and w not in seen:       # trigram needs 3+ characters
            seen.add(w)
            terms.append('"' + w.replace('"', '""') + '"')
    return " OR ".join(terms)


def read_candidates(base: Path, words: list[str], known: set[str]) -> list[dict]:
    """Solved cards matching any of the words in this PC's and the peers' card DBs (read-only).

    Each card gets ``fts`` (0..1, bm25 normalised per DB, bigger is closer). DBs without cards_fts are skipped."""
    query = _fts_query(words)
    if not query:
        return []
    cards: dict[str, dict] = {}
    for path in [base / "overseer.sqlite"] + peer_paths(base):
        if not path.exists():
            continue
        try:
            con = open_peer(path)
            try:
                if not con.execute("select 1 from sqlite_master where name='cards_fts'").fetchone():
                    continue
                rows = con.execute(
                    "select c.card_id, c.project, s.cwd, c.agent, c.problem, c.situation, c.solution, c.outcome, "
                    "coalesce(s.updated_at, c.created_at), bm25(cards_fts) as score from cards_fts "
                    "join cards c using (card_id) left join sessions s on s.source = c.source "
                    "and s.session_id = c.session_id where cards_fts match ? and c.status != 'retired' "
                    "order by score limit ?", (query, CANDIDATES)).fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            continue
        worst = max((-r[-1] for r in rows), default=1.0) or 1.0
        for card_id, project, cwd, agent, problem, situation, solution, outcome, when, bm in rows:
            fts = -bm / worst
            if card_id in cards:
                cards[card_id]["fts"] = max(cards[card_id]["fts"], fts)
                continue
            if not is_solved(outcome or "") or len((solution or "").strip()) < MIN_SOLUTION:
                continue
            try:
                situ = json.loads(situation or "[]")
            except ValueError:
                situ = []
            cards[card_id] = {"id": card_id, "project": resolve_project(project, cwd, known), "agent": agent or "",
                              "problem": (problem or "").strip(), "solution": solution.strip(),
                              "situation": [str(x) for x in situ] if isinstance(situ, list) else [],
                              "date": (when or "")[:10], "fts": fts}
    return list(cards.values())


# ---- tagging and merging -------------------------------------------------------------------

def tag_text(text: str) -> list[str]:
    return [tag for tags in _TOPIC_RES.values() for tag, rx in tags.items() if rx.search(text)]


_WORD = re.compile(r"[0-9a-z_\-\.]{3,}|[가-힣]{2,}")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "when", "not", "are", "was", "을", "를", "에서", "으로"}


def tokens(text: str) -> frozenset[str]:
    return frozenset(w for w in _WORD.findall(text.lower()) if w not in _STOP)


def merge_cards(cards: list[dict]) -> list[dict]:
    """Greedy clustering on token overlap. A lesson keeps the richest card's text and all source ids."""
    lessons: list[dict] = []
    inverted: dict[str, list[int]] = {}
    for card in sorted(cards, key=lambda c: -len(c["solution"])):
        toks = tokens(card["problem"] + " " + card["solution"])
        ptoks = tokens(card["problem"])
        card["_tags"] = tag_text(" ".join([card["problem"], card["solution"], " ".join(card["situation"])]))
        hits: dict[int, int] = {}
        for w in toks:
            for i in inverted.get(w, ()):
                hits[i] = hits.get(i, 0) + 1
        target = None
        for i, n in sorted(hits.items(), key=lambda kv: -kv[1]):
            other = lessons[i]
            small = min(len(toks), len(other["_toks"])) or 1
            if n / small < 0.4:
                break
            union = len(toks | other["_toks"]) or 1
            if n / union >= SIMILAR or (ptoks and other["_ptoks"] and
                                        len(ptoks & other["_ptoks"]) / len(ptoks | other["_ptoks"]) >= 0.6):
                target = other
                break
        if target is None:
            lessons.append({"problem": card["problem"], "solution": card["solution"], "tags": set(card["_tags"]),
                            "sources": [card["id"]], "projects": {card["project"]} - {""}, "pool_general": not card["project"],
                            "date": card["date"], "fts": card.get("fts", 0.0), "_toks": toks, "_ptoks": ptoks})
            for w in toks:
                inverted.setdefault(w, []).append(len(lessons) - 1)
        else:
            target["sources"].append(card["id"])
            if card["project"]:
                target["projects"].add(card["project"])
            target["date"] = max(target["date"], card["date"])
            target["fts"] = max(target["fts"], card.get("fts", 0.0))
    for lesson in lessons:
        digest = hashlib.sha1(("|".join(sorted(lesson["sources"]))).encode()).hexdigest()[:10]
        lesson["id"] = "L" + digest
        lesson["tags"] = sorted(lesson["tags"])
        lesson["projects"] = sorted(lesson["projects"])
        lesson["scope"] = "common" if len(lesson["projects"]) >= 2 or not lesson["projects"] else "project"
        del lesson["_toks"], lesson["_ptoks"]
    return lessons


def primary_topic(lesson: dict) -> str:
    order = list(TOPICS)
    topics = sorted({TAG_TOPIC[t] for t in lesson["tags"]}, key=order.index)
    return topics[0] if topics else "기타"


# ---- rendering -----------------------------------------------------------------------------

def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def render_lesson(lesson: dict, redact: Callable[[str], str], *, with_project: bool = False) -> str:
    ids = ", ".join(s[:8] for s in lesson["sources"][:6]) + (f" 외 {len(lesson['sources']) - 6}" if len(lesson["sources"]) > 6 else "")
    tags = " ".join(f"`{t}`" for t in lesson["tags"][:5])
    where = f" ({', '.join(lesson['projects'][:4])})" if with_project and lesson["projects"] else ""
    text = (f"- **{_clip(lesson['problem'], 220)}**{where}\n  - 해결: {_clip(lesson['solution'], 420)}\n"
            f"  - {tags} · 출처 카드 {ids}" + (f" · {len(lesson['sources'])}회 관찰" if len(lesson["sources"]) > 1 else ""))
    return redact(text)


def make_redactor() -> Redactor:
    return Redactor.from_files(default_secret_files(Path.home()))


# ---- seeding -------------------------------------------------------------------------------

Asker = Callable[[object, dict], dict]


def select(base: Path, kind: str | None, extra_tags: list[str], limit: int, own_project: str = "",
           known: set[str] | None = None) -> list[dict]:
    """Candidates straight from the card DBs (cards_fts), then tag match first and bm25 relevance second."""
    spec = KINDS.get(kind or "", {"tags": [], "query": ""})
    wanted = set(spec["tags"]) | set(extra_tags)
    words = sorted(tokens(spec["query"])) + sorted(wanted)
    if not words:                      # unknown kind and no tags: the environment lessons every project meets
        words = sorted(BASE_TAGS)
    known = known if known is not None else set(known_projects())
    lessons = merge_cards(read_candidates(base, words, known))
    base_tags = BASE_TAGS
    ranked = []
    for l in lessons:
        tags = set(l["tags"])
        hit = len(tags & wanted)
        hit_base = len(tags & base_tags)
        fts = l["fts"]
        # An engine/tool lesson of another stack must not ride in on generic words alone.
        foreign = {t for t in tags if TAG_TOPIC.get(t) == "엔진"} - wanted
        if foreign or (hit == 0 and hit_base == 0 and fts < 0.35):
            continue
        if own_project and l["scope"] == "project" and own_project in l["projects"]:
            continue
        s = 3.0 * hit + 1.0 * min(hit_base, 2) + 3.0 * fts + math.log1p(len(l["sources"])) + (0.5 if l["scope"] == "common" else 0)
        ranked.append((s, l))
    ranked.sort(key=lambda x: -x[0])
    return [l for _, l in ranked[:limit]]


def project_state(path: Path, kind: str | None, tags: list[str]) -> dict:
    readme = ""
    for name in ("README.md", "readme.md", "AGENTS.md", "CLAUDE.md"):
        if (path / name).is_file():
            readme = (path / name).read_text(encoding="utf-8", errors="replace")[:1200]
            break
    files = sorted(p.name for p in path.iterdir())[:40] if path.is_dir() else []
    return {"프로젝트": {"이름": path.name, "종류": kind or "미정", "스택 태그": tags, "최상위 파일": files, "README 앞부분": readme}}


def jev_filter(lessons: list[dict], state: dict, ask: Asker) -> tuple[list[dict], str]:
    """One request, one choice question per candidate. Returns (kept, note); on any failure all candidates stay."""
    if not lessons:
        return lessons, "후보 없음"
    questions = {l["id"]: {"type": "choice",
                           "instructions": ("새로 시작하는 프로젝트에 아래 교훈이 적용되는가? 이 프로젝트의 기술 스택·환경에 해당하는 "
                                            f"문제일 때만 '적용'.\n\n문제: {_clip(l['problem'], 300)}\n해결: {_clip(l['solution'], 400)}"),
                           "criteria": {"적용": "이 프로젝트가 같은 도구·환경·엔진을 쓸 가능성이 있어 이 교훈이 도움이 된다",
                                        "해당 없음": "다른 스택이나 환경의 문제라 이 프로젝트와 무관하다"}}
                 for l in lessons}
    try:
        answers = ask(state, questions)
    except Exception as error:           # a failed call is not an answer: keep the rule-based list
        return lessons, f"Jev 실패({type(error).__name__}): 규칙만 사용"
    kept, dropped = [], 0
    for l in lessons:
        probs = (answers.get(l["id"]) or {}).get("probabilities") or {}
        if float(probs.get("해당 없음", 0) or 0) >= JEV_DROP:
            dropped += 1
        else:
            kept.append(l)
    return kept, f"Jev가 {dropped}개 제외"


def default_asker() -> Asker | None:
    try:
        from all_tomorrow.console import jev
    except Exception:
        return None
    return jev.ask if jev.api_key() else None


def seed(project: Path, *, base: Path | None = None, kind: str | None = None, extra_tags: list[str] | None = None, limit: int = 25,
         use_jev: bool = True, asker: Asker | None = None, redact: Callable[[str], str] | None = None) -> dict:
    """Write the chosen lessons into the project without overwriting anything existing.

    No matching card means no file: returns ``{"lessons": 0, "skipped": ...}``."""
    redact = redact or make_redactor()
    extra_tags = extra_tags or []
    if not project.is_dir():
        raise ValueError("project path must be an existing directory")
    kind = kind or detect_kind(project)
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; known: {sorted(KINDS)}")
    base = base or default_dir()
    lessons = select(base, kind, extra_tags, limit * 2 if use_jev else limit, own_project=project.name)
    if not lessons:
        return {"kind": kind, "lessons": 0, "skipped": f"맞는 해결 카드 없음({base})"}
    note = "규칙만 사용"
    if use_jev:
        ask = asker or default_asker()
        if ask:
            lessons, note = jev_filter(lessons, project_state(project, kind, sorted(set(KINDS.get(kind or "", {}).get("tags", [])) | set(extra_tags))), ask)
        else:
            note = "Jev 키 없음: 규칙만 사용"
    lessons = lessons[:limit]
    if not lessons:
        return {"kind": kind, "lessons": 0, "skipped": f"후보 모두 제외됨: {note}", "note": note}
    docs = project / "docs"
    target = docs / "knowhow.md"
    if target.exists() and MARKER not in target.read_text(encoding="utf-8", errors="replace"):
        target = docs / "knowhow-seed.md"          # someone's own knowhow.md: keep it
    docs.mkdir(exist_ok=True)
    body = [MARKER, f"# {project.name} 시작 노하우", "",
            f"All Tomorrow가 다른 프로젝트·세션에서 풀린 문제 중 이 프로젝트({kind or '종류 미정'})에 맞을 만한 것을 골랐다. "
            "참고용이며 지금 상황에 맞는지는 읽는 쪽이 판단한다. 출처 카드는 `oracle_ask`로 찾는다.",
            f"선별: 신탁 카드 DB 전문 검색 + 태그 일치, {note}. 생성 {datetime.now(timezone.utc).strftime('%Y-%m-%d')}", ""]
    groups: dict[str, list[dict]] = {}
    for lesson in lessons:
        groups.setdefault(primary_topic(lesson), []).append(lesson)
    for topic in [*TOPICS, "기타"]:
        if topic in groups:
            body += [f"## {topic}", ""] + [render_lesson(l, redact, with_project=True) for l in groups[topic]] + [""]
    target.write_text("\n".join(body), encoding="utf-8")
    link = f"- 시작 노하우(다른 프로젝트에서 모은 교훈): [{target.relative_to(project).as_posix()}]({target.relative_to(project).as_posix()})"
    linked = _add_link(project, link, target.relative_to(project).as_posix())
    return {"kind": kind, "file": str(target), "lessons": len(lessons), "link_in": linked, "note": note}


def _add_link(project: Path, link: str, rel: str) -> str | None:
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = project / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if rel not in text:
                path.write_text(text.rstrip("\n") + "\n\n" + link + "\n", encoding="utf-8")
            return name
    (project / "AGENTS.md").write_text(link + "\n", encoding="utf-8")
    return "AGENTS.md"


# ---- command line --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="all_tomorrow.overseer knowhow")
    parser.add_argument("--dir", type=Path, default=None, help="overseer store folder (default: store.default_dir())")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="put suitable lessons from the oracle's card DBs into a new project's docs/knowhow.md")
    s.add_argument("project", type=Path)
    s.add_argument("--kind", choices=sorted(KINDS), default=None, help="default: guessed from the files")
    s.add_argument("--tag", action="append", default=[], help="extra stack tag, e.g. docker")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--no-jev", action="store_true")
    args = parser.parse_args(argv)
    result = seed(args.project, base=args.dir, kind=args.kind, extra_tags=args.tag, limit=args.limit,
                  use_jev=not args.no_jev)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
