"""04C — Laptop Workspace Resolver verification."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from all_tomorrow.workspace import (
    DirtyTreeObservation,
    SourceIdentityMismatchError,
    WorkspaceBinding,
    WorkspaceBindingConflictError,
    WorkspaceEscapeError,
    WorkspaceResolver,
    WorkspaceResolutionError,
)


def _resolver_with(binding: WorkspaceBinding) -> WorkspaceResolver:
    r = WorkspaceResolver()
    r.register(binding)
    return r


def test_normal_resolve(tmp_path: Path) -> None:
    root = tmp_path / "repos"
    ws = root / "proj"
    ws.mkdir(parents=True)
    r = _resolver_with(WorkspaceBinding("codex", "p1", str(ws), str(root)))
    res = r.resolve("codex", "p1", frozenset({str(root)}))
    assert res.resolved_path == os.path.realpath(str(ws))
    assert res.allowed_root == os.path.realpath(str(root))


def test_unknown_project(tmp_path: Path) -> None:
    r = WorkspaceResolver()
    with pytest.raises(WorkspaceResolutionError):
        r.resolve("codex", "nope", frozenset({str(tmp_path)}))


def test_duplicate_binding(tmp_path: Path) -> None:
    b = WorkspaceBinding("codex", "p1", str(tmp_path), str(tmp_path))
    r = _resolver_with(b)
    with pytest.raises(WorkspaceBindingConflictError):
        r.register(b)


def test_nonexistent_path(tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    r = _resolver_with(WorkspaceBinding("codex", "p1", str(missing), str(tmp_path)))
    with pytest.raises(WorkspaceResolutionError):
        r.resolve("codex", "p1", frozenset({str(tmp_path)}))


@pytest.mark.skipif(os.name == "nt", reason="symlink creation may need privilege on Windows")
def test_symlink_escape_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "escape"
    os.symlink(outside, link)  # link inside root pointing out
    r = _resolver_with(WorkspaceBinding("codex", "p1", str(link), str(root)))
    with pytest.raises(WorkspaceEscapeError):
        r.resolve("codex", "p1", frozenset({str(root)}))


def test_path_outside_allowed_root_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    r = _resolver_with(WorkspaceBinding("codex", "p1", str(other), str(root)))
    with pytest.raises(WorkspaceEscapeError):
        r.resolve("codex", "p1", frozenset({str(root)}))


def test_resolver_root_not_in_worker_allowed_roots(tmp_path: Path) -> None:
    root = tmp_path / "root"
    ws = root / "proj"
    ws.mkdir(parents=True)
    r = _resolver_with(WorkspaceBinding("codex", "p1", str(ws), str(root)))
    # Worker's allowlist does NOT include the resolver root → double-check fails.
    with pytest.raises(WorkspaceEscapeError):
        r.resolve("codex", "p1", frozenset({str(tmp_path / "elsewhere")}))


def test_logical_source_mismatch(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    r = _resolver_with(WorkspaceBinding(
        "codex", "p1", str(ws), str(tmp_path),
        expected_source_ref="https://github.com/innollia/all-tomorrow.git",
    ))
    with pytest.raises(SourceIdentityMismatchError):
        r.resolve("codex", "p1", frozenset({str(tmp_path)}),
                  observed_source_ref="https://github.com/someone/other.git")


def test_logical_source_match_tolerates_git_suffix(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    r = _resolver_with(WorkspaceBinding(
        "codex", "p1", str(ws), str(tmp_path),
        expected_source_ref="https://github.com/innollia/all-tomorrow",
    ))
    res = r.resolve("codex", "p1", frozenset({str(tmp_path)}),
                    observed_source_ref="https://github.com/innollia/all-tomorrow.git")
    assert res.project_id == "p1"


def test_dirty_tree_requires_user_decision() -> None:
    r = WorkspaceResolver()
    dirty = DirtyTreeObservation(is_dirty=True, current_branch="main", head_ref="abc123")
    assert r.requires_user_decision(dirty, requested_baseline_ref="abc123") is True

    clean_wrong_base = DirtyTreeObservation(is_dirty=False, current_branch="main", head_ref="abc123")
    assert r.requires_user_decision(clean_wrong_base, requested_baseline_ref="def456") is True

    clean_right_base = DirtyTreeObservation(is_dirty=False, current_branch="main", head_ref="abc123")
    assert r.requires_user_decision(clean_right_base, requested_baseline_ref="abc123") is False


def test_catalog_stores_no_host_local_path() -> None:
    # The catalog surface (domain models.py Project/source refs) must not carry a
    # host-local path field; that lives only in WorkspaceBinding (local, ignored).
    import all_tomorrow.workspace as ws_mod
    from all_tomorrow.contracts import Project

    proj_fields = set(getattr(Project, "__dataclass_fields__", {}).keys())
    for banned in ("path", "checkout_path", "local_path", "cwd"):
        assert banned not in proj_fields, f"catalog Project leaks host path field: {banned}"
    # And the binding is where the path lives.
    assert "path" in ws_mod.WorkspaceBinding.__dataclass_fields__
