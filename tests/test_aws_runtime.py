"""04D — AWS single-node runtime: deployment-contract invariants (offline).

Verifies the committed IaC/config satisfies the contract that the L3 live
reboot/restore/upgrade tests then exercise on a real instance:
- every image pinned by digest (no mutable tag) — D-LOCK-13
- no literal secret in deploy/ ; secrets are env / file references
- no protected approval credential referenced on the node — D-LOCK-14 / 04D-04
- only the app port is publicly bound
- the runbook documents backup/restore + deploy/rollback + reconciliation
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

COMPOSE = Path("deploy/docker-compose.yaml")
RUNBOOK = Path("docs/deploy/aws-single-node.md")


def test_04d_all_images_digest_pinned() -> None:
    cfg = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = cfg["services"]
    assert services, "compose defines no services"
    for name, svc in services.items():
        image = svc.get("image", "")
        assert "@sha256:" in image, f"{name} image is not digest-pinned: {image!r}"
        assert not re.search(r":latest\b", image), f"{name} uses mutable :latest"


def test_04d_no_literal_secret_in_deploy() -> None:
    for f in Path("deploy").rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("#") or not s:
                continue
            # A literal provider/master key would be an sk-... or AKIA... value.
            assert not re.search(r"\bsk-[A-Za-z0-9]{8,}", s), f"literal key in {f}: {line!r}"
            assert "AKIA" not in s, f"literal AWS key in {f}: {line!r}"


def test_04d_no_protected_credential_on_node() -> None:
    # The node config must not reference an approval/deployment protected secret.
    for f in (COMPOSE, Path("deploy/all-tomorrow.service")):
        text = f.read_text(encoding="utf-8").lower()
        for banned in ("approval_secret", "approval_credential", "deploy_key", "deployment_credential"):
            assert banned not in text, f"{f} references a protected credential: {banned}"


def test_04d_only_app_port_is_public() -> None:
    cfg = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    for name, svc in cfg["services"].items():
        for mapping in svc.get("ports", []) or []:
            m = str(mapping)
            public = not m.startswith("127.0.0.1:")
            if public:
                # Only the app's 8080 may be publicly bound.
                assert name == "all-tomorrow-app" and m.endswith("8080:8080"), (
                    f"{name} exposes a non-app public port: {m}"
                )


def test_04d_runbook_covers_contract() -> None:
    text = RUNBOOK.read_text(encoding="utf-8").lower()
    for section in ("deployment contract", "backup", "restore", "rollback",
                    "reconciliation", "network / security", "iam"):
        assert section in text, f"runbook missing section: {section}"
    # Each L3 requirement id is accounted for in the failure-scenario table.
    for req in ("04d-01", "04d-02", "04d-03", "04d-05", "04d-07"):
        assert req in text, f"runbook does not map requirement {req}"
