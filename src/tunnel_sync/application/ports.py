"""Small capability interfaces for application workflows."""

import threading
from typing import Any, Callable, Protocol


class CloudflareReader(Protocol):
    def read(self, endpoint: str, token: str, method: str = "GET") -> dict[str, Any]:
        raise NotImplementedError


class CloudflareWriter(Protocol):
    def mutate(self, endpoint: str, token: str, method: str, data: dict | None = None) -> dict[str, Any]:
        raise NotImplementedError


class DockerInventoryReader(Protocol):
    def request(self, path: str, method: str = "GET", **kwargs) -> Any:
        raise NotImplementedError


class DockerEventSource(Protocol):
    def listen_events(
        self,
        on_event: Callable[[dict], None],
        stop_event: threading.Event | None = None,
        socket_path: str | None = None,
    ) -> None:
        raise NotImplementedError

    def close_events(self) -> None:
        raise NotImplementedError


class ConnectorRestarter(Protocol):
    def restart(self, name: str) -> None:
        raise NotImplementedError


class TokenStore(Protocol):
    def read(self) -> str:
        raise NotImplementedError

    def write(self, token: str) -> None:
        raise NotImplementedError


class SyncMetrics(Protocol):
    def record_sync_run(
        self, duration: float, status: str = "success", discovered_count: int = 0, safety_tripped: bool = False
    ) -> None:
        raise NotImplementedError

    def record_dns_op(self, operation: str, count: float = 1.0) -> None:
        raise NotImplementedError

    def record_ingress_op(self, operation: str, count: float = 1.0) -> None:
        raise NotImplementedError

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        raise NotImplementedError


class Notifications(Protocol):
    def get_status(self) -> dict[str, Any]:
        raise NotImplementedError

    def dispatch_sync(
        self,
        event_type: str,
        title: str,
        message: str,
        level: str = "error",
        details: dict[str, Any] | None = None,
        force: bool = False,
    ) -> tuple[bool, str]:
        raise NotImplementedError
