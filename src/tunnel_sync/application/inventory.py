"""Explicit discovery availability; an empty successful inventory is usable."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class InventoryUnavailableError(RuntimeError):
    """An inventory adapter could not reach its source."""


class InventoryStatus(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class InventoryResult:
    status: InventoryStatus
    services: tuple[dict[str, Any], ...] = ()
    containers: tuple[dict[str, Any], ...] = ()
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.status == InventoryStatus.AVAILABLE
