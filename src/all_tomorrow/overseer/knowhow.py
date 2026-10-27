"""Cross-project know-how: cards -> per-project lesson files, a common file, and seeds for new projects.

build: reads the distilled cards (this PC + peers, read-only), keeps solved ones, tags them by
topic, merges near-duplicate lessons (source card ids are kept) and writes
``<out>/projects/<project>.md``, ``<out>/common.md`` and ``<out>/index.json``. No model call.

seed: picks lessons for a new project from index.json by tag match + FTS relevance, optionally asks
Jev (one request, one question per candidate) whether each applies, and writes ``docs/knowhow.md``
into the project. Existing files are never overwritten; AGENTS.md / CLAUDE.md only gets a link line.

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
MAX_PER_PROJECT = 60
MAX_COMMON = 100
MIN_SOLUTION = 20
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


def read_cards(base: Path, known: set[str]) -> list[dict]:
    """Solved cards of this PC and the peers, deduplicated by card id."""
    cards: dict[str, dict] = {}
    stores = [base / "overseer.sqlite"] + peer_paths(base)
    for path in stores:
        if not path.exists():
            continue
        try:
            con = open_peer(path)
            rows = con.execute(
                "select c.card_id, c.project, s.cwd, c.agent, c.problem, c.situation, c.attempts, c.solution, "
                "c.outcome, coalesce(s.updated_at, c.created_at) from cards c left join sessions s "
                "on s.source = c.source and s.session_id = c.session_id where c.status != 'retired'").fetchall()
            con.close()
        except sqlite3.Error:
            continue
        for card_id, project, cwd, agent, problem, situation, attempts, solution, outcome, when in rows:
            if card_id in cards or not is_solved(outcome or "") or len((solution or "").strip()) < MIN_SOLUTION:
                continue
            try:
                situ = json.loads(situation or "[]")
            except ValueError:
                situ = []
            cards[card_id] = {"id": card_id, "project": resolve_project(project, cwd, known), "agent": agent or "",
                              "problem": (problem or "").strip(), "solution": solution.strip(),
                              "situation": [str(x) for x in situ] if isinstance(situ, list) else [],
                              "date": (when or "")[:10]}
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
                            "date": card["date"], "_toks": toks, "_ptoks": ptoks})
            for w in toks:
                inverted.setdefault(w, []).append(len(lessons) - 1)
        else:
            target["sources"].append(card["id"])
            if card["project"]:
                target["projects"].add(card["project"])
            target["date"] = max(target["date"], card["date"])
    for lesson in lessons:
        digest = hashlib.sha1(("|".join(sorted(lesson["sources"]))).encode()).hexdigest()[:10]
        lesson["id"] = "L" + digest
        lesson["tags"] = sorted(lesson["tags"])
        lesson["projects"] = sorted(lesson["projects"])
        del lesson["_toks"], lesson["_ptoks"]
    return lessons


def score(lesson: dict) -> float:
    return len(lesson["sources"]) + 0.5 * len(lesson["projects"]) + (0.001 * int(lesson["date"].replace("-", "") or 0) / 1e4)


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


def render_file(title: str, intro: str, lessons: list[dict], redact: Callable[[str], str], total: int,
                with_project: bool = False) -> str:
    out = [f"# {title}", "", intro, f"교훈 {len(lessons)}개" + (f" (전체 {total}개 중 관찰 횟수 순)" if total > len(lessons) else ""),
           f"생성: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC · `python -m all_tomorrow.overseer knowhow build`로 갱신 (손으로 고치지 말 것)", ""]
    groups: dict[str, list[dict]] = {}
    for lesson in lessons:
        groups.setdefault(primary_topic(lesson), []).append(lesson)
    for topic in [*TOPICS, "기타"]:
        if topic in groups:
            out += [f"## {topic}", ""] + [render_lesson(item, redact, with_project=with_project) for item in groups[topic]] + [""]
    return "\n".join(out)


def slug(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", name).strip("_.") or "project"


def knowhow_dir() -> Path:
    return Path(os.environ.get("ALL_TOMORROW_KNOWHOW_DIR") or REPO_ROOT / ".artifacts" / "knowhow")


def make_redactor() -> Redactor:
    return Redactor.from_files(default_secret_files(Path.home()))


def build(base: Path, out: Path, *, redact: Callable[[str], str] | None = None, known: set[str] | None = None) -> dict:
    redact = redact or make_redactor()
    known = known if known is not None else set(known_projects())
    cards = read_cards(base, known)
    lessons = merge_cards(cards)
    common = [l for l in lessons if len(l["projects"]) >= 2 or (not l["projects"] and len(l["sources"]) >= 2)
              or (not l["projects"] and l["tags"])]
    common_ids = {l["id"] for l in common}
    per_project: dict[str, list[dict]] = {}
    for lesson in lessons:
        if lesson["id"] not in common_ids:
            for project in lesson["projects"]:
                per_project.setdefault(project, []).append(lesson)
    (out / "projects").mkdir(parents=True, exist_ok=True)
    for old in (out / "projects").glob("*.md"):
        old.unlink()
    files: dict[str, int] = {}
    for project, items in sorted(per_project.items()):
        items.sort(key=score, reverse=True)
        if len(items) < 2:      # one lone lesson is not a bundle
            continue
        chosen = items[:MAX_PER_PROJECT]
        path = out / "projects" / f"{slug(project)}.md"
        path.write_text(render_file(f"{project} 노하우", "이 프로젝트에서 겪고 푼 문제들. 같은 문제는 합쳤고 출처 카드는 oracle(`oracle_ask`)에서 찾을 수 있다.",
                                    chosen, redact, len(items)), encoding="utf-8")
        files[f"projects/{path.name}"] = len(chosen)
    common.sort(key=score, reverse=True)
    top = common[:MAX_COMMON]
    (out / "common.md").write_text(render_file("공통 교훈", "둘 이상의 프로젝트에서 반복되었거나 특정 프로젝트에 매이지 않는 환경·도구 교훈.",
                                               top, redact, len(common), with_project=True), encoding="utf-8")
    files["common.md"] = len(top)
    index = [{k: l[k] for k in ("id", "problem", "solution", "tags", "projects", "sources", "date")}
             | {"scope": "common" if l["id"] in common_ids else "project"} for l in lessons]
    for item in index:
        item["problem"], item["solution"] = redact(item["problem"]), redact(item["solution"])
    (out / "index.json").write_text(json.dumps({"built": datetime.now(timezone.utc).isoformat(), "lessons": index},
                                               ensure_ascii=False), encoding="utf-8")
    return {"cards": len(cards), "lessons": len(lessons), "files": files, "common": len(common), "dir": str(out)}


# ---- seeding -------------------------------------------------------------------------------

Asker = Callable[[object, dict], dict]


def load_index(out: Path) -> list[dict]:
    path = out / "index.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} 없음: 먼저 `knowhow build`를 실행하세요")
    return json.loads(path.read_text(encoding="utf-8"))["lessons"]


def select(lessons: list[dict], kind: str | None, extra_tags: list[str], limit: int, own_project: str = "") -> list[dict]:
    """Tag match first, FTS relevance (bm25 over an in-memory trigram index) second."""
    spec = KINDS.get(kind or "", {"tags": [], "query": ""})
    wanted = set(spec["tags"]) | set(extra_tags)
    base = BASE_TAGS
    con = sqlite3.connect(":memory:")
    con.execute("create virtual table f using fts5(lid unindexed, body, tokenize='trigram')")
    con.executemany("insert into f values (?,?)", [(l["id"], l["problem"] + " " + l["solution"]) for l in lessons])
    relevance: dict[str, float] = {}
    terms = [w for w in tokens(spec["query"] + " " + " ".join(extra_tags)) if len(w) >= 3]
    if terms:
        q = " OR ".join('"' + w.replace('"', '""') + '"' for w in terms)
        try:
            rows = con.execute("select lid, bm25(f) from f where f match ?", (q,)).fetchall()
        except sqlite3.Error:
            rows = []
        worst = max((-r[1] for r in rows), default=1.0) or 1.0
        relevance = {lid: -b / worst for lid, b in rows}      # 0..1, bigger is closer
    con.close()
    ranked = []
    for l in lessons:
        tags = set(l["tags"])
        hit = len(tags & wanted)
        hit_base = len(tags & base)
        fts = relevance.get(l["id"], 0.0)
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


def seed(project: Path, out: Path, *, kind: str | None = None, extra_tags: list[str] | None = None, limit: int = 25,
         use_jev: bool = True, asker: Asker | None = None, redact: Callable[[str], str] | None = None) -> dict:
    """Write the chosen lessons into the project without overwriting anything existing."""
    redact = redact or make_redactor()
    extra_tags = extra_tags or []
    if not project.is_dir():
        raise ValueError("project path must be an existing directory")
    kind = kind or detect_kind(project)
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; known: {sorted(KINDS)}")
    lessons = select(load_index(out), kind, extra_tags, limit * 2 if use_jev else limit, own_project=project.name)
    note = "규칙만 사용"
    if use_jev:
        ask = asker or default_asker()
        if ask:
            lessons, note = jev_filter(lessons, project_state(project, kind, sorted(set(KINDS.get(kind or "", {}).get("tags", [])) | set(extra_tags))), ask)
        else:
            note = "Jev 키 없음: 규칙만 사용"
    lessons = lessons[:limit]
    docs = project / "docs"
    target = docs / "knowhow.md"
    if target.exists() and MARKER not in target.read_text(encoding="utf-8", errors="replace"):
        target = docs / "knowhow-seed.md"          # someone's own knowhow.md: keep it
    docs.mkdir(exist_ok=True)
    body = [MARKER, f"# {project.name} 시작 노하우", "",
            f"All Tomorrow가 다른 프로젝트·세션에서 풀린 문제 중 이 프로젝트({kind or '종류 미정'})에 맞을 만한 것을 골랐다. "
            "참고용이며 지금 상황에 맞는지는 읽는 쪽이 판단한다. 출처 카드는 `oracle_ask`로 찾는다.",
            f"선별: 태그 일치 + 전문 검색 관련도, {note}. 생성 {datetime.now(timezone.utc).strftime('%Y-%m-%d')}", ""]
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
    parser.add_argument("--dir", type=Path, default=None, help="overseer store folder")
    parser.add_argument("--out", type=Path, default=None, help="knowhow output folder")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="cards -> .artifacts/knowhow/projects/*.md, common.md, index.json (no model call)")
    s = sub.add_parser("seed", help="put suitable lessons into a new project's docs/knowhow.md")
    s.add_argument("project", type=Path)
    s.add_argument("--kind", choices=sorted(KINDS), default=None, help="default: guessed from the files")
    s.add_argument("--tag", action="append", default=[], help="extra stack tag, e.g. docker")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--no-jev", action="store_true")
    args = parser.parse_args(argv)
    out = args.out or knowhow_dir()
    if args.cmd == "build":
        result = build(args.dir or default_dir(), out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    result = seed(args.project, out, kind=args.kind, extra_tags=args.tag, limit=args.limit, use_jev=not args.no_jev)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
