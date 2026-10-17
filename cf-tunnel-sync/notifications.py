"""Actionable webhook notification dispatcher for sync failures and safety aborts."""

import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("cf-tunnel-sync")


def detect_webhook_type(url: str, explicit_type: Optional[str] = None) -> str:
    """Detect webhook provider type (discord, slack, generic) from URL or configuration."""
    if explicit_type and explicit_type.strip().lower() not in ("", "auto"):
        return explicit_type.strip().lower()

    url_lower = url.lower()
    if "discord.com/api/webhooks" in url_lower:
        return "discord"
    if "hooks.slack.com" in url_lower:
        return "slack"
    return "generic"


class NotificationDispatcher:
    """Dispatches throttled alerts to Discord, Slack, or generic webhook endpoints."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        webhook_type: str = "auto",
        cooldown_seconds: float = 300.0,
    ):
        self.webhook_url = webhook_url or os.getenv("NOTIFICATION_WEBHOOK_URL", "").strip()
        self.explicit_type = webhook_type or os.getenv("NOTIFICATION_WEBHOOK_TYPE", "auto").strip()
        try:
            self.cooldown_seconds = float(os.getenv("NOTIFICATION_COOLDOWN_SECONDS", str(cooldown_seconds)))
        except (ValueError, TypeError):
            self.cooldown_seconds = 300.0

        # In-memory alert cache: event_hash -> last_dispatched_timestamp
        self._sent_cache: Dict[str, float] = {}

    @property
    def is_enabled(self) -> bool:
        """Return True if a valid webhook URL is configured."""
        return bool(self.webhook_url and self.webhook_url.startswith("http"))

    @property
    def resolved_type(self) -> str:
        """Return resolved webhook type (discord, slack, generic)."""
        return detect_webhook_type(self.webhook_url, self.explicit_type)

    def _generate_event_hash(self, event_type: str, title: str) -> str:
        raw = f"{event_type}:{title}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def should_throttle(self, event_type: str, title: str) -> bool:
        """Check if an identical alert has already been sent within the cooldown window."""
        h = self._generate_event_hash(event_type, title)
        now = time.time()
        last_sent = self._sent_cache.get(h)
        if last_sent is not None and (now - last_sent) < self.cooldown_seconds:
            return True
        return False

    def mark_sent(self, event_type: str, title: str):
        """Mark an event as sent in the cache."""
        h = self._generate_event_hash(event_type, title)
        self._sent_cache[h] = time.time()

    def format_payload(
        self,
        event_type: str,
        title: str,
        message: str,
        level: str = "error",
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Format JSON payload tailored for Discord, Slack, or Generic HTTP consumers."""
        provider = self.resolved_type
        iso_time = datetime.now(timezone.utc).isoformat()
        details_dict = details or {}

        if provider == "slack":
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "🚨 Cloudflare Tunnel Sync Alert"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{title}*\n{message}",
                    },
                },
            ]
            if details_dict:
                detail_lines = "\n".join(f"• *{k}*: `{v}`" for k, v in details_dict.items())
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": detail_lines},
                    }
                )
            return {
                "text": f"[cf-tunnel-sync] {title}: {message}",
                "blocks": blocks,
            }

        elif provider == "discord":
            color = 15158332 if level.lower() == "error" else 15844367  # Red for error, gold for warn
            embed: Dict[str, Any] = {
                "title": f"🚨 {title}",
                "description": message,
                "color": color,
                "timestamp": iso_time,
                "footer": {"text": "cf-docker-tunnel-sync"},
            }
            if details_dict:
                embed["fields"] = [
                    {"name": str(k), "value": f"`{str(v)[:100]}`", "inline": True}
                    for k, v in list(details_dict.items())[:10]
                ]
            return {
                "content": f"**[cf-tunnel-sync ALERT]** {title}",
                "embeds": [embed],
            }

        # Default Generic JSON format
        return {
            "event": event_type,
            "level": level.lower(),
            "title": title,
            "message": message,
            "timestamp": iso_time,
            "details": details_dict,
        }

    async def dispatch(
        self,
        event_type: str,
        title: str,
        message: str,
        level: str = "error",
        details: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> Tuple[bool, str]:
        """Dispatch webhook asynchronously with throttling and safe error capture."""
        if not self.is_enabled:
            return False, "Webhook notifications disabled or URL not configured"

        if not force and self.should_throttle(event_type, title):
            logger.info("Webhook alert throttled for %s: '%s' (cooldown active)", event_type, title)
            return False, "Alert throttled by cooldown"

        payload = self.format_payload(event_type, title, message, level=level, details=details)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.webhook_url, json=payload)
                if resp.status_code >= 400:
                    err_msg = f"Webhook POST failed with status {resp.status_code}: {resp.text[:200]}"
                    logger.warning(err_msg)
                    return False, err_msg

                self.mark_sent(event_type, title)
                logger.info("Successfully dispatched webhook alert: '%s'", title)
                return True, "Alert delivered successfully"
        except Exception as e:
            err_msg = f"Webhook dispatch error: {e}"
            logger.warning(err_msg)
            return False, err_msg

    def dispatch_sync(
        self,
        event_type: str,
        title: str,
        message: str,
        level: str = "error",
        details: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> Tuple[bool, str]:
        """Dispatch webhook synchronously with throttling and safe error capture."""
        if not self.is_enabled:
            return False, "Webhook notifications disabled or URL not configured"

        if not force and self.should_throttle(event_type, title):
            logger.info("Webhook alert throttled for %s: '%s' (cooldown active)", event_type, title)
            return False, "Alert throttled by cooldown"

        payload = self.format_payload(event_type, title, message, level=level, details=details)

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(self.webhook_url, json=payload)
                if resp.status_code >= 400:
                    err_msg = f"Webhook POST failed with status {resp.status_code}: {resp.text[:200]}"
                    logger.warning(err_msg)
                    return False, err_msg

                self.mark_sent(event_type, title)
                logger.info("Successfully dispatched webhook alert: '%s'", title)
                return True, "Alert delivered successfully"
        except Exception as e:
            err_msg = f"Webhook dispatch error: {e}"
            logger.warning(err_msg)
            return False, err_msg


# Default global dispatcher instance
default_dispatcher = NotificationDispatcher()
