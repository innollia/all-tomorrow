from __future__ import annotations

from dataclasses import dataclass

from all_tomorrow.contracts import ContractError


@dataclass(frozen=True, slots=True)
class ModelRoute:
    alias: str
    provider: str
    model: str
    credential_ref: str
    capabilities: frozenset[str]
    status: str = "unknown"
    fallback_aliases: tuple[str, ...] = ()
    privacy_tags: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ModelRequest:
    alias: str
    required_capabilities: frozenset[str] = frozenset()
    privacy_tags: frozenset[str] = frozenset()


class ModelRouter:
    def __init__(self, routes: tuple[ModelRoute, ...]) -> None:
        self._routes = {route.alias: route for route in routes}
        if len(self._routes) != len(routes):
            raise ContractError("model aliases must be unique")

    def select(self, request: ModelRequest) -> ModelRoute:
        primary = self._routes.get(request.alias)
        if primary is None:
            raise ContractError(f"unknown model alias: {request.alias}")
        candidates = (primary,) + tuple(
            self._routes[alias]
            for alias in primary.fallback_aliases
            if alias in self._routes
        )
        for route in candidates:
            if (
                route.status == "available"
                and request.required_capabilities <= route.capabilities
                and request.privacy_tags <= route.privacy_tags
            ):
                return route
        raise ContractError(f"no available model route satisfies alias {request.alias}")


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    provider: str
    account: str
    key_ref: str
    status: str
    models: frozenset[str]

    def __post_init__(self) -> None:
        if not self.key_ref or self.key_ref.lower().startswith(("sk-", "api-")):
            raise ContractError("credential records require an opaque secret-store reference, not a key value")

