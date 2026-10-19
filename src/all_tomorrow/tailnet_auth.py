"""Tailnet identity login: requests from the user's own Tailscale devices skip the password.

A tailnet packet's source address is authenticated by WireGuard, so asking the host's
tailscaled "who owns 100.x.y.z?" (LocalAPI whois) is a real identity check. Headers
would not be: any client could forge them. Requests through the public HTTPS proxy
(Caddy) arrive from the proxy's address, never match a tailnet range, and keep using
the password login.

Enabled only when ALL_TOMORROW_TAILNET_LOGINS lists the allowed Tailscale login names.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import time
from collections.abc import Callable

import httpx

log = logging.getLogger(__name__)

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")       # Tailscale CGNAT range
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")  # Tailscale ULA range
DEFAULT_SOCKET = "/var/run/tailscale/tailscaled.sock"
POSITIVE_TTL = 300
NEGATIVE_TTL = 30


def is_tailnet_address(host: str | None) -> bool:
    try:
        address = ipaddress.ip_address((host or "").split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    network = TAILNET_V4 if address.version == 4 else TAILNET_V6
    return address in network


def localapi_whois(socket_path: str) -> Callable[[str], str | None]:
    """whois via the host tailscaled LocalAPI unix socket (mounted into the container)."""
    def whois(host: str) -> str | None:
        transport = httpx.HTTPTransport(uds=socket_path)
        with httpx.Client(transport=transport, timeout=2.0) as client:
            response = client.get("http://local-tailscaled.sock/localapi/v0/whois", params={"addr": host})
        if response.status_code != 200:
            return None
        return (response.json().get("UserProfile") or {}).get("LoginName")
    return whois


class TailnetIdentity:
    def __init__(self, allowed_logins: set[str], whois: Callable[[str], str | None]) -> None:
        self.allowed = {login.strip().lower() for login in allowed_logins if login.strip()}
        self._whois = whois
        self._cache: dict[str, tuple[float, str | None]] = {}

    def login_for(self, host: str | None) -> str | None:
        """The allowed Tailscale login that owns this source address, else None."""
        if not self.allowed or not host or not is_tailnet_address(host):
            return None
        hit = self._cache.get(host)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        try:
            login = (self._whois(host) or "").lower() or None
        except (httpx.HTTPError, OSError, ValueError) as error:
            log.warning("tailnet whois failed for %s: %s", host, type(error).__name__)
            login = None
        result = login if login in self.allowed else None
        self._cache[host] = (time.monotonic() + (POSITIVE_TTL if result else NEGATIVE_TTL), result)
        return result

    @classmethod
    def from_environment(cls) -> TailnetIdentity | None:
        logins = os.environ.get("ALL_TOMORROW_TAILNET_LOGINS", "")
        if not logins.strip():
            return None
        socket_path = os.environ.get("ALL_TOMORROW_TAILSCALE_SOCKET", DEFAULT_SOCKET)
        return cls(set(logins.split(",")), localapi_whois(socket_path))
