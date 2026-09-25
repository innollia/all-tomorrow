"""Verification for 00D Architecture fitness checks."""

import pytest
from scripts.check_architecture_fitness import (
    check_domain_backend_imports,
    check_work_execution_ref_invariant,
    check_migration_ownership,
    check_protected_credentials,
    check_mutable_latest_tags,
    run_all_checks,
)


def test_architecture_fitness_domain_pure_imports() -> None:
    """Domain package must not import selected backend internal types."""
    violations = check_domain_backend_imports()
    assert len(violations) == 0, f"Domain import violations: {violations}"


def test_architecture_fitness_work_run_linkage() -> None:
    """Work table must not own ExecutionRef; Run linkage must be used."""
    violations = check_work_execution_ref_invariant()
    assert len(violations) == 0, f"Work execution_ref invariant violations: {violations}"


def test_architecture_fitness_migration_system_tables() -> None:
    """Migrations must not own backend system tables."""
    violations = check_migration_ownership()
    assert len(violations) == 0, f"Migration ownership violations: {violations}"


def test_architecture_fitness_no_protected_credentials() -> None:
    """Config files must not contain hardcoded live credentials."""
    violations = check_protected_credentials()
    assert len(violations) == 0, f"Credential violations: {violations}"


def test_architecture_fitness_no_mutable_latest_tags() -> None:
    """Deploy configs must not use mutable latest tags."""
    violations = check_mutable_latest_tags()
    assert len(violations) == 0, f"Mutable tag violations: {violations}"


def test_architecture_fitness_all_clear() -> None:
    """All checks run via runner function pass cleanly."""
    assert run_all_checks() is True
