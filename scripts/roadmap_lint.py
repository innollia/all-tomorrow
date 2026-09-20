#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "roadmap" / "manifest.json"
VALID_STATUS = {"개발중", "개발완료", "시작안했음", "선행작업 대기"}
STATUS_RE = re.compile(r"상태:\s*(?:\*\*)?([^\n*]+)")
REQ_RE = re.compile(r"\b(S\d+-[A-Z0-9]+-\d{2})\b")
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def markdown_status(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    match = STATUS_RE.search(text)
    return match.group(1).strip() if match else None

def check_cycle(graph: dict[str, list[str]]) -> list[str]:
    visiting: set[str] = set()
    done: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        if node in done:
            return []
        if node in visiting:
            i = stack.index(node)
            return stack[i:] + [node]
        visiting.add(node)
        stack.append(node)
        for dep in graph.get(node, []):
            cycle = visit(dep)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        done.add(node)
        return []

    for node in graph:
        cycle = visit(node)
        if cycle:
            return cycle
    return []

def local_markdown_links(path: Path) -> list[Path]:
    text = path.read_text(encoding="utf-8")
    out: list[Path] = []
    for target in LINK_RE.findall(text):
        if "://" in target or target.startswith("#") or target.startswith("mailto:"):
            continue
        target = target.split("#", 1)[0]
        if not target:
            continue
        out.append((path.parent / target).resolve())
    return out

def lint(root: Path = ROOT, manifest_path: Path = MANIFEST) -> list[str]:
    errors: list[str] = []
    data = load_manifest(manifest_path)
    packets = data.get("packets", [])
    by_id: dict[str, dict] = {}
    children: dict[str, list[str]] = defaultdict(list)
    requirement_owners: dict[str, str] = {}

    if data.get("schema_version") != 1:
        errors.append("manifest schema_version must be 1")

    for packet in packets:
        pid = packet.get("packet_id")
        if not pid:
            errors.append("packet missing packet_id")
            continue
        if pid in by_id:
            errors.append(f"duplicate packet_id: {pid}")
            continue
        by_id[pid] = packet
        status = packet.get("status")
        if status not in VALID_STATUS:
            errors.append(f"{pid}: invalid status {status!r}")
        p = root / packet.get("path", "")
        if not p.is_file():
            errors.append(f"{pid}: roadmap path missing: {packet.get('path')}")
            continue
        md_status = markdown_status(p)
        if md_status is not None and md_status != status:
            errors.append(f"{pid}: manifest status {status!r} != markdown status {md_status!r}")
        parent = packet.get("parent_id")
        if parent:
            children[parent].append(pid)

        text = p.read_text(encoding="utf-8")
        prefix = packet.get("requirement_prefix")
        for req in REQ_RE.findall(text):
            previous = requirement_owners.get(req)
            if previous and previous != pid:
                errors.append(f"duplicate requirement id {req}: {previous}, {pid}")
            requirement_owners[req] = pid
            if prefix and not req.startswith(prefix):
                errors.append(f"{pid}: requirement {req} does not match prefix {prefix}")

    for pid, packet in by_id.items():
        parent = packet.get("parent_id")
        if parent and parent not in by_id:
            errors.append(f"{pid}: unknown parent {parent}")
        for dep in packet.get("prerequisites", []):
            if dep not in by_id:
                errors.append(f"{pid}: unknown prerequisite {dep}")

    graph = {pid: list(p.get("prerequisites", [])) for pid, p in by_id.items()}
    cycle = check_cycle(graph)
    if cycle:
        errors.append("dependency cycle: " + " -> ".join(cycle))

    for pid, packet in by_id.items():
        if packet.get("status") == "개발완료":
            for dep in packet.get("prerequisites", []):
                if by_id[dep].get("status") != "개발완료":
                    errors.append(f"{pid}: completed before prerequisite {dep}")
            direct = children.get(pid, [])
            incomplete = [c for c in direct if by_id[c].get("status") != "개발완료"]
            if incomplete:
                errors.append(f"{pid}: completed while children incomplete: {', '.join(incomplete)}")

        prereqs_complete = all(by_id[d].get("status") == "개발완료" for d in packet.get("prerequisites", []))
        if packet.get("status") == "선행작업 대기" and prereqs_complete:
            errors.append(f"{pid}: waiting but all declared prerequisites are complete")
        if packet.get("status") in {"시작안했음", "개발중", "개발완료"} and not prereqs_complete:
            errors.append(f"{pid}: status {packet.get('status')} but prerequisites are incomplete")

    for contract_name, rel in data.get("contracts", {}).items():
        if not (root / rel).is_file():
            errors.append(f"contract {contract_name}: missing {rel}")

    docs = root / "docs" / "roadmap"
    for md in docs.rglob("*.md"):
        for target in local_markdown_links(md):
            try:
                target.relative_to(root)
            except ValueError:
                continue
            if not target.exists():
                errors.append(f"{md.relative_to(root)}: broken local link -> {target.relative_to(root)}")

    forbidden = {
        "docs/roadmap/stage-01-researcher/01-durable-kernel/01c-durable-queue.md",
    }
    for rel in forbidden:
        if (root / rel).exists():
            errors.append(f"stale forbidden roadmap path exists: {rel}")

    return errors

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    errors = lint(ROOT, args.manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"{len(errors)} roadmap lint error(s)")
        return 1
    print("roadmap lint: OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
