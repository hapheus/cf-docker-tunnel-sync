"""Compatibility imports for the historical notifications module."""

from tunnel_sync.adapters.notifications import NotificationDispatcher as NotificationDispatcher
from tunnel_sync.adapters.notifications import detect_webhook_type as detect_webhook_type
from tunnel_sync.compat.defaults import default_dispatcher as default_dispatcher

__all__ = ["NotificationDispatcher", "detect_webhook_type", "default_dispatcher"]
