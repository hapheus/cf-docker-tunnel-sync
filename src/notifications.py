"""Compatibility imports for the historical notifications module."""

import warnings

from tunnel_sync.adapters.notifications import NotificationDispatcher as NotificationDispatcher
from tunnel_sync.adapters.notifications import detect_webhook_type as detect_webhook_type
from tunnel_sync.compat.defaults import default_dispatcher as default_dispatcher

warnings.warn(
    "Use 'tunnel_sync.adapters.notifications' instead; historical 'notifications' module is frozen.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["NotificationDispatcher", "detect_webhook_type", "default_dispatcher"]
