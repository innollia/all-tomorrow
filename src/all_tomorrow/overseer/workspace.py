"""커밋 없이 사본에서 시험하고, 파일별 이전 바이트로 되돌린다."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from all_tomorrow.improve.promotion import DeploymentPlan, DeploymentRef

EXCLUDED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
            ".artifacts", ".stversions", ".stfolder", ".codex", ".agents", ".claude", ".aws", ".ssh",
            ".kiro", ".gemini", "key-pool.env", "credentials.json", ".credentials.json"}


def excluded(name: str) -> bool:
    return name in EXCLUDED or name.startswith(".env") or name.endswith((".pem", ".key"))


def tree(root: Path) -> dict[str, str]:
    result = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(folder) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError("링크가 있는 프로젝트는 자동 변경하지 않습니다")
        dirs[:] = [n for n in dirs if not excluded(n)]
        for name in files:
            if not excluded(name):
                path = Path(folder) / name
                result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def digest(files: dict) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def save(path: Path, data: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


class ProjectChange:
    def __init__(self, root: Path, artifact: Path):
        self.root, self.artifact = root.resolve(), artifact.resolve()
        self.before, self.candidate = self.artifact / "before", self.artifact / "candidate"
        self.manifest = self.artifact / "promotion.json"

    def prepare(self) -> None:
        baseline = tree(self.root)
        self.artifact.mkdir(parents=True, exist_ok=False)
        ignore = lambda folder, names: [n for n in names if excluded(n)]
        shutil.copytree(self.root, self.before, ignore=ignore)
        if tree(self.before) != baseline or tree(self.root) != baseline:
            raise ValueError("사본 생성 중 원본이 바뀌었습니다")
        shutil.copytree(self.before, self.candidate)
        save(self.manifest, {"root": str(self.root), "baseline": baseline, "state": "prepared"})

    def changed(self) -> list[str]:
        before, after = tree(self.before), tree(self.candidate)
        if before.keys() - after.keys():
            raise PermissionError("파일 삭제는 사용자에게 물어야 합니다")
        return [n for n in after if before.get(n) != after[n]]

    def frozen_changed(self, protected: list[str]) -> bool:
        for name in self.changed():
            # 시험 자체와 제어 경계는 후보가 바꿀 수 없다. 새 시험은 추가 가능하다.
            if name in tree(self.before) and (name.startswith("tests/") or name in protected
                    or name.startswith(("config/", "deploy/", ".github/", "migrations/"))):
                return True
        return False

    def inspect_current(self) -> str:
        return digest(tree(self.root))

    def validate_candidate(self, candidate_ref: str) -> bool:
        return bool(self.changed()) and digest(tree(self.candidate)) == candidate_ref

    def plan(self, candidate_ref: str, current_ref: str) -> DeploymentPlan:
        return DeploymentPlan(candidate_ref, current_ref, tuple(self.changed()))

    def apply(self, plan: DeploymentPlan) -> DeploymentRef:
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data.update(state="applying", changed=list(plan.steps), candidate=tree(self.candidate))
        save(self.manifest, data)  # 쓰기 전에 복구에 필요한 상태를 남긴다.
        try:
            for name in plan.steps:
                target = self.root / name
                # 매 파일 쓰기 직전 원본 전체를 다시 확인한다.
                expected = dict(data["baseline"])
                for done in data.get("applied", []):
                    expected[done] = data["candidate"][done]
                if tree(self.root) != expected:
                    raise ValueError("반영 중 원본 변경 감지")
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(target.name + f".all-tomorrow-{self.artifact.name}.tmp")
                if temp.exists():
                    raise ValueError("임시 파일 경로가 이미 사용 중입니다")
                data["temporary"] = temp.relative_to(self.root).as_posix()
                save(self.manifest, data)
                shutil.copy2(self.candidate / name, temp)
                temp.replace(target)
                data.setdefault("applied", []).append(name)
                save(self.manifest, data)
        except BaseException:
            self.rollback(plan.previous_ref, DeploymentRef(self.artifact.name, plan.candidate_ref, plan.previous_ref))
            raise
        return DeploymentRef(self.artifact.name, plan.candidate_ref, plan.previous_ref)

    def verify(self, deployment: DeploymentRef) -> bool:
        # 시험한 사본과 실제 반영본이 같은 바이트인지 확인한다.
        return self.inspect_current() == deployment.candidate_ref

    def rollback(self, previous_ref: str, deployment: DeploymentRef | None = None) -> str:
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        temporary = data.get("temporary")
        if temporary and temporary not in data["baseline"]:
            temp = self.root / temporary
            if temp.is_file():
                # 교체 직전 중단된 파일도 삭제하지 않고 백업 옆에 보관한다.
                shutil.move(str(temp), str(self.artifact / "interrupted-write.tmp"))
        # 새 파일도 삭제하지 않고 보관한다. 사용자/다른 세션이 바꾼 파일은 덮어쓰지 않는다.
        for name in data.get("changed", []):
            current = tree(self.root).get(name)
            original = data["baseline"].get(name)
            if current == original:
                continue
            if current != data.get("candidate", {}).get(name):
                raise ValueError("되돌릴 파일을 다른 세션이 변경했습니다")
            target = self.root / name
            if original is None:
                archive = self.artifact / "reverted-new" / name
                archive.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(archive))
            else:
                shutil.copy2(self.before / name, target)
        data["state"] = "rolled_back"
        save(self.manifest, data)
        return self.inspect_current()

    def finish(self) -> None:
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["state"] = "promoted"
        save(self.manifest, data)
