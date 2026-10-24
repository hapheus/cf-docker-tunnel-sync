"""Compatibility imports for the historical metrics module."""

from tunnel_sync.adapters.metrics import PrometheusRegistry as PrometheusRegistry
from tunnel_sync.compat.defaults import metrics_registry as metrics_registry

__all__ = ["PrometheusRegistry", "metrics_registry"]
