"""04C — Laptop Workspace Resolver.

Separates logical project/source identity (in the catalog) from a host-local
checkout path (a local, ignored binding), and stops a worker from escaping the
allowed workspace root. The catalog never stores a host-local path.

Resolution double-verifies the filesystem boundary: the resolver checks the
binding is under its ``allowed_root`` AND the worker's own ``allowed_roots`` must
contain the same normalized root, and symlink/junction escapes are rejected via
``realpath`` normalization.

Dirty-tree policy is observe-only: the resolver never auto-stashes/resets/checks
out. A mutation Work whose baseline differs from the observed HEAD is surfaced as
NEED_USER (or an explicit disposable worktree), never silently overwritten.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from all_tomorrow.domain.errors import DomainError


class WorkspaceResolutionError(DomainError):
    """A workspace could not be resolved safely (unknown, missing, or unsafe)."""


class WorkspaceEscapeError(WorkspaceResolutionError):
    """The resolved path escapes its allowed root (traversal/symlink/junction)."""


class WorkspaceBindingConflictError(WorkspaceResolutionError):
    """A duplicate (executor_id, project_id) binding was registered."""


class SourceIdentityMismatchError(WorkspaceResolutionError):
    """The checkout's repo/remote identity does not match the expected source."""


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    """Local, ignored mapping of a logical project to a host checkout path."""

    executor_id: str
    project_id: str
    path: str
    allowed_root: str
    expected_source_ref: str | None = None  # e.g. git remote URL, optionally @ref

    def __post_init__(self) -> None:
        for f in ("executor_id", "project_id", "path", "allowed_root"):
            if not getattr(self, f) or not str(getattr(self, f)).strip():
                raise ValueError(f"WorkspaceBinding.{f} must be non-empty")


@dataclass(frozen=True, slots=True)
class DirtyTreeObservation:
    is_dirty: bool
    current_branch: str | None
    head_ref: str | None
    untracked_present: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedWorkspace:
    executor_id: str
    project_id: str
    resolved_path: str      # realpath, guaranteed under allowed_root
    allowed_root: str       # realpath
    dirty: DirtyTreeObservation | None = None


def _norm(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _is_under(child: str, root: str) -> bool:
    """True iff ``child`` is ``root`` or a descendant, using normalized paths."""
    child_n = _norm(child)
    root_n = _norm(root)
    try:
        common = os.path.commonpath([child_n, root_n])
    except ValueError:
        return False  # different drives on Windows
    return common == root_n


class WorkspaceResolver:
    """Resolves logical (executor_id, project_id) to a safe host checkout path."""

    def __init__(self) -> None:
        self._bindings: dict[tuple[str, str], WorkspaceBinding] = {}

    def register(self, binding: WorkspaceBinding) -> None:
        key = (binding.executor_id, binding.project_id)
        if key in self._bindings:
            raise WorkspaceBindingConflictError(
                f"duplicate binding for executor={binding.executor_id} project={binding.project_id}"
            )
        self._bindings[key] = binding

    def resolve(
        self,
        executor_id: str,
        project_id: str,
        worker_allowed_roots: frozenset[str],
        *,
        observed_source_ref: str | None = None,
        observe_dirty: "DirtyTreeObservation | None" = None,
    ) -> ResolvedWorkspace:
        """Resolve to a checkout path, double-verifying the filesystem boundary.

        ``worker_allowed_roots`` is the worker's own root allowlist; the resolved
        root must appear there too (independent second check). ``observe_dirty``
        and ``observed_source_ref`` are injected by the caller (which runs git);
        the resolver stays pure and never shells out.
        """
        binding = self._bindings.get((executor_id, project_id))
        if binding is None:
            raise WorkspaceResolutionError(
                f"unknown workspace: executor={executor_id} project={project_id}"
            )

        path_n = _norm(binding.path)
        root_n = _norm(binding.allowed_root)

        # (5) missing / non-directory → explicit unavailable.
        if not os.path.isdir(path_n):
            raise WorkspaceResolutionError(f"workspace path is missing or not a directory: {binding.path}")

        # (1)(2)(4) normalized path must be under normalized allowed_root; realpath
        # already resolved symlinks/junctions, so an escape via link fails here.
        if not _is_under(path_n, root_n):
            raise WorkspaceEscapeError(
                f"workspace {path_n} escapes allowed_root {root_n}"
            )

        # (3) the worker's own allowlist must contain the same normalized root.
        worker_roots_n = {_norm(r) for r in worker_allowed_roots}
        if root_n not in worker_roots_n:
            raise WorkspaceEscapeError(
                f"allowed_root {root_n} not in worker allowed_roots {sorted(worker_roots_n)}"
            )

        # (6) logical source identity mismatch → reject.
        if binding.expected_source_ref and observed_source_ref is not None:
            if not _source_matches(binding.expected_source_ref, observed_source_ref):
                raise SourceIdentityMismatchError(
                    f"source mismatch: expected {binding.expected_source_ref}, observed {observed_source_ref}"
                )

        return ResolvedWorkspace(
            executor_id=executor_id,
            project_id=project_id,
            resolved_path=path_n,
            allowed_root=root_n,
            dirty=observe_dirty,
        )

    def requires_user_decision(
        self,
        observation: DirtyTreeObservation,
        requested_baseline_ref: str | None,
    ) -> bool:
        """True when a mutation Work must stop for NEED_USER instead of proceeding.

        A dirty tree, or an observed HEAD different from the requested baseline,
        means the resolver will NOT silently overwrite the user's checkout.
        """
        if observation.is_dirty or observation.untracked_present:
            return True
        if requested_baseline_ref is not None and observation.head_ref is not None:
            return observation.head_ref != requested_baseline_ref
        return False


def _source_matches(expected: str, observed: str) -> bool:
    """Compare repo/remote identities, tolerant of .git suffix and trailing slash."""
    def canon(s: str) -> str:
        s = s.strip().rstrip("/")
        if s.endswith(".git"):
            s = s[:-4]
        return s.lower()

    exp_repo, _, exp_ref = expected.partition("@")
    obs_repo, _, obs_ref = observed.partition("@")
    if canon(exp_repo) != canon(obs_repo):
        return False
    if exp_ref and obs_ref and exp_ref != obs_ref:
        return False
    return True
