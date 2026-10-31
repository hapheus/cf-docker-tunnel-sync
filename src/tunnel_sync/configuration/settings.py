"""Explicit environment snapshots, preserving existing lookup precedence."""

import logging
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypeVar, overload

logger = logging.getLogger("cf-tunnel-sync")
T = TypeVar("T")


@dataclass(frozen=True)
class Settings:
    """One configuration snapshot per application/run; secrets stay out of repr."""

    environment: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        env = dict(self.environment)
        if "BASIC_AUTH_USERNAME" in env and not env.get("DASHBOARD_USERNAME"):
            logger.warning(
                "Configuration note: 'BASIC_AUTH_USERNAME' is deprecated and will be removed in a future release. Please use 'DASHBOARD_USERNAME' instead."
            )
            env["DASHBOARD_USERNAME"] = env["BASIC_AUTH_USERNAME"]
        if "BASIC_AUTH_PASSWORD" in env and not env.get("DASHBOARD_PASSWORD"):
            logger.warning(
                "Configuration note: 'BASIC_AUTH_PASSWORD' is deprecated and will be removed in a future release. Please use 'DASHBOARD_PASSWORD' instead."
            )
            env["DASHBOARD_PASSWORD"] = env["BASIC_AUTH_PASSWORD"]
        object.__setattr__(self, "environment", MappingProxyType(env))

    @overload
    def get(self, name: str) -> str | None:
        """Lookup setting without default."""

    @overload
    def get(self, name: str, default: str) -> str:
        """Lookup setting with str default."""

    @overload
    def get(self, name: str, default: T) -> str | T:
        """Lookup setting with generic default."""

    def get(self, name: str, default=None):
        return self.environment.get(name, default)

    @property
    def domain(self) -> str:
        return self.get("DOMAIN_NAME", "").strip().rstrip(".").lower()

    @property
    def token(self) -> str:
        return (self.get("CLOUDFLARE_API_TOKEN") or self.get("CLOUDFLARE_TOKEN") or "").strip()

    @property
    def dry_run(self) -> bool:
        return self.get("DRY_RUN", "false").lower() in ("true", "1", "yes")
