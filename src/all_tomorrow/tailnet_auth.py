"""Tailnet login: the owner's own Tailscale devices skip the password.

`tailscale serve` on the node terminates HTTPS for the tailnet name and adds a
`Tailscale-User-Login` header naming the tailnet user who opened the connection.
Headers can be forged by anyone who reaches the app directly, so the app trusts it
ONLY on a dedicated port (ALL_TOMORROW_TAILSCALE_SERVE_PORT) that is published on the
node's loopback only — the one place `tailscale serve` connects from. The main port
(public Caddy, tailnet :8080, device agents) never honours the header.

Why not check the source address instead: on the node, Docker's port publishing and
Tailscale hand the app a bridge/loopback address (measured 2026-10-19: a tailnet
request arrived as 172.18.0.1), so the tailnet address is not visible to the app.

Enabled only when ALL_TOMORROW_TAILNET_LOGINS lists the allowed Tailscale logins.
"""
from __future__ import annotations

import os
from typing import Any

LOGIN_HEADER = "tailscale-user-login"


class TailnetIdentity:
    def __init__(self, allowed_logins: set[str], trusted_port: int) -> None:
        self.allowed = {login.strip().lower() for login in allowed_logins if login.strip()}
        self.trusted_port = trusted_port

    def from_trusted_port(self, scope: dict[str, Any]) -> bool:
        server = scope.get("server")
        return bool(server) and len(server) > 1 and server[1] == self.trusted_port

    def login_for(self, scope: dict[str, Any], headers: Any) -> str | None:
        """The allowed Tailscale login for this request, else None."""
        if not self.allowed or not self.from_trusted_port(scope):
            return None
        login = (headers.get(LOGIN_HEADER) or "").strip().lower()
        return login if login in self.allowed else None

    def https(self, scope: dict[str, Any], headers: Any) -> bool:
        # tailscale serve terminates TLS and forwards plain HTTP; on the trusted port only.
        return self.from_trusted_port(scope) and (headers.get("x-forwarded-proto") or "").lower() == "https"

    @classmethod
    def from_environment(cls) -> TailnetIdentity | None:
        logins = os.environ.get("ALL_TOMORROW_TAILNET_LOGINS", "")
        port = os.environ.get("ALL_TOMORROW_TAILSCALE_SERVE_PORT", "")
        if not logins.strip() or not port.strip():
            return None
        return cls(set(logins.split(",")), int(port))
