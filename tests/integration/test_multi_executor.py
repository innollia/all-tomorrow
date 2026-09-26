"""Stage 3.3C — Multi-executor workspace verification (S3-33C-01..04)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from all_tomorrow.domain.ids import utc_now
from all_tomorrow.workspaces import (
    DirtyResetRefused,
    SourceMismatchError,
    Workspace,
    WorkspaceProvenance,
    WorkspaceState,
    register_host,
)


def _prov(dirty=False, source="https://git/repo", branch="main"):
    return WorkspaceProvenance(source_url=source, branch=branch, head_sha="abc123",
                               dirty=dirty, root_path="/ws/wt1", provisioned_by="fleet")


def _ws(state=WorkspaceState.READY_CLEAN, dirty=False, age=timedelta(0), host="h1"):
    return Workspace(name="wt1", host=host, state=state, provenance=_prov(dirty=dirty),
                     observed_at=utc_now() - age)


# S3-33C-01: offline / stale workspace is not usable-now.
def test_33c_01_offline_freshness() -> None:
    assert _ws(state=WorkspaceState.OFFLINE).usable_now() is False
    assert _ws(age=timedelta(hours=1)).usable_now() is False   # stale
    assert _ws().usable_now() is True


# S3-33C-02: a dirty checkout is not auto-reset; reconciliation required.
def test_33c_02_dirty_no_auto_reset() -> None:
    ws = _ws(state=WorkspaceState.READY_DIRTY, dirty=True)
    with pytest.raises(DirtyResetRefused):
        ws.prepare_clean()
    assert ws.state == WorkspaceState.RECONCILIATION_REQUIRED


# S3-33C-03: source mismatch is rejected.
def test_33c_03_source_mismatch_reject() -> None:
    ws = _ws()
    with pytest.raises(SourceMismatchError):
        ws.assert_source("https://git/OTHER", "main")
    with pytest.raises(SourceMismatchError):
        ws.assert_source("https://git/repo", "feature")
    ws.assert_source("https://git/repo", "main")   # match → no raise


# S3-33C-04: adding a host reuses the logical workspace name (no core-name branch).
def test_33c_04_host_addition_same_name() -> None:
    a = register_host("wt1", "hostA", _prov())
    b = register_host("wt1", "hostB", _prov())
    assert a.name == b.name == "wt1"
    assert a.host != b.host
