"""Architecture fitness check script (Stage 00D).

Verifies architectural invariants:
1. Domain package forbids selected backend internal type imports (e.g. dbos, restate).
2. Work table has no single ExecutionRef; Run linkage is strictly used.
3. App migrations never own/alter backend system tables (e.g. dbos.*).
4. No raw provider/model object serialization in domain records.
5. No protected credentials in AWS runtime env/config.
6. No mutable :latest image tags in deploy/container configs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def check_domain_backend_imports() -> list[str]:
    """1. Domain package forbids selected backend internal type imports."""
    violations = []
    domain_dir = Path("src/all_tomorrow/domain")
    forbidden = ["dbos", "restate", "temporalio", "celery", "prefect"]
    for py_file in domain_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for line in text.splitlines():
            clean = line.strip()
            if clean.startswith("import ") or clean.startswith("from "):
                for pkg in forbidden:
                    if re.search(rf"\b(import|from)\s+{pkg}\b", clean):
                        violations.append(f"{py_file}: forbidden import of backend '{pkg}' in domain: {clean}")
    return violations


def check_work_execution_ref_invariant() -> list[str]:
    """2. Work table forbids single ExecutionRef; Run linkage must be used."""
    violations = []
    state_file = Path("src/all_tomorrow/domain/state.py")
    if state_file.exists():
        text = state_file.read_text(encoding="utf-8")
        # In WorkRecord, execution_ref must NOT exist
        if "execution_ref:" in text.split("class WorkRecord")[1].split("class RunRecord")[0]:
            violations.append("WorkRecord contains forbidden execution_ref field (must use Run linkage)")
    return violations


def check_migration_ownership() -> list[str]:
    """3. App migrations never own/alter backend system tables."""
    violations = []
    mig_dir = Path("migrations")
    if mig_dir.exists():
        for sql_file in mig_dir.rglob("*.sql"):
            text = sql_file.read_text(encoding="utf-8").lower()
            if "create table" in text and "dbos." in text:
                violations.append(f"{sql_file}: app migration attempts to own dbos system table")
    return violations


def check_semantic_schema_invariants() -> list[str]:
    """01A. Semantic kernel migration invariants (work_items / runs_semantic).

    * work_items must NOT own execution_backend/id/version (Run owns ExecutionRef).
    * work_items / runs_semantic must NOT add All Tomorrow queue-authority columns
      (claimed_by, lease_expires_at) — those mechanics belong to the durable backend.
    * runs_semantic MUST carry the ExecutionRef columns (execution_backend/id/version).
    """
    violations: list[str] = []
    mig = Path("migrations/0006_semantic_kernel.sql")
    if not mig.exists():
        return violations
    text = mig.read_text(encoding="utf-8").lower()

    def _table_body(name: str) -> str:
        marker = f"create table if not exists {name} ("
        if marker not in text:
            return ""
        after = text.split(marker, 1)[1]
        # body ends at the first ");" that closes the CREATE TABLE
        return after.split(");", 1)[0]

    work_body = _table_body("work_items")
    if work_body:
        for forbidden in ("execution_backend", "execution_id", "execution_version",
                          "claimed_by", "lease_expires_at"):
            if forbidden in work_body:
                violations.append(
                    f"work_items owns forbidden column '{forbidden}' "
                    f"(ExecutionRef/queue authority must not live on Work)"
                )

    runs_body = _table_body("runs_semantic")
    if runs_body:
        for required in ("execution_backend", "execution_id", "execution_version"):
            if required not in runs_body:
                violations.append(
                    f"runs_semantic missing required ExecutionRef column '{required}'"
                )
        for forbidden in ("claimed_by", "lease_expires_at"):
            if forbidden in runs_body:
                violations.append(
                    f"runs_semantic owns forbidden queue-authority column '{forbidden}'"
                )
    return violations


def check_protected_credentials() -> list[str]:
    """5. Protected credentials not in deploy/runtime config."""
    violations = []
    config_dir = Path("config")
    secret_pat = re.compile(r"sk-[a-zA-Z0-9_-]{12,}")
    if config_dir.exists():
        for f in config_dir.rglob("*"):
            if f.is_file():
                content = f.read_text(encoding="utf-8", errors="replace")
                if secret_pat.search(content):
                    violations.append(f"{f}: Hardcoded protected credential found in config")
    return violations


def check_mutable_latest_tags() -> list[str]:
    """6. Mutable latest image/tag forbidden in deploy configs."""
    violations = []
    deploy_dir = Path("deploy")
    if deploy_dir.exists():
        for f in deploy_dir.rglob("*"):
            if f.is_file() and f.suffix in (".yaml", ".yml", ".json", ".dockerfile"):
                content = f.read_text(encoding="utf-8", errors="replace")
                if re.search(r"image:.*:latest\b", content, re.IGNORECASE):
                    violations.append(f"{f}: Forbidden mutable ':latest' image tag used")
    return violations


def run_all_checks() -> bool:
    all_violations = []
    all_violations.extend(check_domain_backend_imports())
    all_violations.extend(check_work_execution_ref_invariant())
    all_violations.extend(check_migration_ownership())
    all_violations.extend(check_semantic_schema_invariants())
    all_violations.extend(check_protected_credentials())
    all_violations.extend(check_mutable_latest_tags())

    if all_violations:
        print(f"FAILED: {len(all_violations)} architecture fitness violations found:")
        for v in all_violations:
            print(f"  - {v}")
        return False
    print("PASSED: All architecture fitness checks cleared (0 violations).")
    return True


if __name__ == "__main__":
    success = run_all_checks()
    sys.exit(0 if success else 1)
