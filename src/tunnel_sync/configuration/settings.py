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

    def _bool(self, name: str, default: bool = False) -> bool:
        raw = self.get(name)
        if raw is None or raw == "":
            return default
        return raw.strip().lower() in ("true", "1", "yes")

    def _int(self, name: str, default: int) -> int:
        raw = self.get(name)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            value = int(str(raw).strip())
        except (ValueError, TypeError):
            return default
        return value if value >= 0 else default

    @property
    def dry_run(self) -> bool:
        return self._bool("DRY_RUN", False)

    @property
    def dashboard_auth_required(self) -> bool:
        """Opt-in strict mode (ISS-02); off by default, preserves current open behavior."""
        return self._bool("DASHBOARD_AUTH_REQUIRED", False)

    @property
    def preserve_manual_roots(self) -> bool:
        """Opt-in manual-root preservation policy (ISS-08); off by default."""
        return self._bool("PRESERVE_MANUAL_ROOTS", False)

    @property
    def tombstone_persistence_enabled(self) -> bool:
        """Opt-in tombstone persistence (ISS-11); off by default (in-memory)."""
        return self._bool("TOMBSTONE_PERSISTENCE_ENABLED", False)

    @property
    def tombstone_persistence_path(self) -> str:
        return (
            self.get("TOMBSTONE_PERSISTENCE_PATH", "/etc/cloudflared/tombstones.json")
            or "/etc/cloudflared/tombstones.json"
        )

    @property
    def heartbeat_enabled(self) -> bool:
        """Opt-in heartbeat logging for long-running syncs (ISS-14); off by default."""
        return self._bool("SYNC_HEARTBEAT_ENABLED", False)

    @property
    def dns_immediate_cleanup(self) -> bool:
        return self._bool("DNS_IMMEDIATE_CLEANUP", False)

    @property
    def allow_mass_deletions(self) -> bool:
        return self._bool("ALLOW_MASS_DELETIONS", False)

    @property
    def dashboard_bind_address(self) -> str:
        return (self.get("DASHBOARD_BIND_ADDRESS") or "0.0.0.0").strip() or "0.0.0.0"

    @property
    def max_deletions(self) -> int:
        """Preserve precedence: MAX_DELETIONS_PER_SYNC > MAX_DELETIONS_PER_RUN > 3 (ISS-17)."""
        for name in ("MAX_DELETIONS_PER_SYNC", "MAX_DELETIONS_PER_RUN"):
            raw = self.get(name)
            if raw and str(raw).strip().isdigit():
                return int(str(raw).strip())
        return 3
