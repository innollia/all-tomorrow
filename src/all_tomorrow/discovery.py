"""Stage 3.3A — External Discovery Sandbox.

Exploring a new package/repo/tool is done from untrusted input in an isolated
sandbox: README/tool instructions carry no authority, no production credential is
injected, network/filesystem access is explicitly bounded, and source/version/
hash provenance is recorded. A sandbox success is NOT production trust —
adopting a discovery into production must pass the ordinary self-change /
protected-change rail (03E classify).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from all_tomorrow.domain.errors import DomainError


class DiscoveryError(DomainError):
    pass


class CredentialCanaryTripped(DiscoveryError):
    """The sandbox tried to read a production credential — denied."""


class SandboxEscape(DiscoveryError):
    """The sandbox tried to reach outside its declared network/fs policy."""


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    allow_network: bool = False
    allowed_fs_roots: tuple[str, ...] = ()
    resource_budget_units: int = 100


@dataclass(frozen=True, slots=True)
class DiscoverySource:
    name: str
    version: str
    content_hash: str
    origin_url: str


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    source: DiscoverySource
    install_commands: tuple[str, ...]
    provenance_recorded: bool
    sandbox_ok: bool
    production_ready: bool = False   # never True from the sandbox alone


# Names that, if a sandbox process reads them, indicate a credential exfil attempt.
_CREDENTIAL_CANARIES = ("AWS_SECRET_ACCESS_KEY", "AT_GATEWAY_MASTER_KEY", "AT_OPENAI_API_KEY",
                        "id_rsa", ".aws/credentials")


def instruction_authority(_readme_text: str) -> bool:
    """README / tool instructions are untrusted DATA — never grant authority."""
    return False


def check_credential_access(accessed_names: list[str]) -> None:
    for n in accessed_names:
        if any(canary.lower() in n.lower() for canary in _CREDENTIAL_CANARIES):
            raise CredentialCanaryTripped(f"sandbox attempted to read credential: {n}")


def check_sandbox_boundary(policy: SandboxPolicy, *, network_used: bool, fs_paths: list[str]) -> None:
    if network_used and not policy.allow_network:
        raise SandboxEscape("network access outside sandbox policy")
    import os
    for p in fs_paths:
        rp = os.path.realpath(p)
        if not any(rp.startswith(os.path.realpath(root)) for root in policy.allowed_fs_roots):
            raise SandboxEscape(f"filesystem access outside sandbox roots: {p}")


def run_discovery(
    source: DiscoverySource,
    policy: SandboxPolicy,
    *,
    accessed_credential_names: list[str] | None = None,
    network_used: bool = False,
    fs_paths: list[str] | None = None,
    install_commands: tuple[str, ...] = (),
) -> DiscoveryResult:
    """Run a discovery in the sandbox, enforcing all guards. Records provenance."""
    check_credential_access(accessed_credential_names or [])
    check_sandbox_boundary(policy, network_used=network_used, fs_paths=fs_paths or [])
    # Provenance is always recorded (source/version/hash/origin).
    return DiscoveryResult(
        source=source, install_commands=install_commands,
        provenance_recorded=True, sandbox_ok=True, production_ready=False,
    )


def is_production_adoptable(_result: DiscoveryResult) -> bool:
    """Sandbox success alone never authorizes production adoption (03E rail required)."""
    return False
