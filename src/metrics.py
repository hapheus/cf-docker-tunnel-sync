"""Compatibility imports for the historical metrics module."""

import warnings

from tunnel_sync.adapters.metrics import PrometheusRegistry as PrometheusRegistry
from tunnel_sync.compat.defaults import metrics_registry as metrics_registry

warnings.warn(
    "Use 'tunnel_sync.adapters.metrics' instead; historical 'metrics' module is frozen.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["PrometheusRegistry", "metrics_registry"]
