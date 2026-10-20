"""Process defaults for historical imports only; production factories own instances."""

from tunnel_sync.adapters.metrics import PrometheusRegistry
from tunnel_sync.adapters.notifications import NotificationDispatcher

metrics_registry = PrometheusRegistry()
default_dispatcher = NotificationDispatcher(metrics=metrics_registry)
