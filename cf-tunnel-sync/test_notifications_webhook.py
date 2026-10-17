"""Hermetic tests for actionable webhook dispatcher for sync failures and safety aborts (Issue #56 - R09)."""

import unittest
from unittest.mock import MagicMock, patch

import httpx
from notifications import NotificationDispatcher, detect_webhook_type


class TestNotificationsWebhook(unittest.TestCase):
    def test_detect_webhook_type(self):
        """Verify URL auto-detection and explicit type overrides."""
        discord_url = "https://discord.com/api/webhooks/12345/abcdef"
        slack_url = "https://hooks.slack.com/services/T00/B00/X00"
        generic_url = "https://alerts.myhomelab.org/webhook"

        self.assertEqual(detect_webhook_type(discord_url), "discord")
        self.assertEqual(detect_webhook_type(slack_url), "slack")
        self.assertEqual(detect_webhook_type(generic_url), "generic")

        # Explicit override
        self.assertEqual(detect_webhook_type(generic_url, explicit_type="slack"), "slack")
        self.assertEqual(detect_webhook_type(slack_url, explicit_type="generic"), "generic")

    def test_slack_payload_format(self):
        """Verify Slack formatted payload conforms to Slack Block Kit structure."""
        dispatcher = NotificationDispatcher(webhook_url="https://hooks.slack.com/services/test")
        payload = dispatcher.format_payload(
            event_type="SYNC_FAILURE",
            title="Sync Failed",
            message="Cloudflare API error",
            level="error",
            details={"service": "web"},
        )

        self.assertIn("text", payload)
        self.assertIn("blocks", payload)
        self.assertEqual(payload["blocks"][0]["type"], "header")
        self.assertIn("Cloudflare Tunnel Sync Alert", payload["blocks"][0]["text"]["text"])
        self.assertEqual(payload["blocks"][1]["type"], "section")
        self.assertIn("*Sync Failed*", payload["blocks"][1]["text"]["text"])

    def test_discord_payload_format(self):
        """Verify Discord payload contains embeds with color and fields."""
        dispatcher = NotificationDispatcher(webhook_url="https://discord.com/api/webhooks/test")
        payload = dispatcher.format_payload(
            event_type="SAFETY_GUARD_TRIPPED",
            title="Blast-Radius Deletion Guard",
            message="Planned deletions exceed limit",
            level="error",
            details={"deletions": 5, "limit": 3},
        )

        self.assertIn("content", payload)
        self.assertIn("embeds", payload)
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "🚨 Blast-Radius Deletion Guard")
        self.assertEqual(embed["color"], 15158332)  # Red
        self.assertIn("fields", embed)
        field_names = [f["name"] for f in embed["fields"]]
        self.assertIn("deletions", field_names)
        self.assertIn("limit", field_names)

    def test_generic_payload_format(self):
        """Verify Generic payload contains clean JSON schema."""
        dispatcher = NotificationDispatcher(webhook_url="https://example.com/webhook")
        payload = dispatcher.format_payload(
            event_type="SYNC_DEGRADED",
            title="Degraded State",
            message="DNS record sync failed",
            level="warning",
            details={"dns_failed": True},
        )

        self.assertEqual(payload["event"], "SYNC_DEGRADED")
        self.assertEqual(payload["level"], "warning")
        self.assertEqual(payload["title"], "Degraded State")
        self.assertEqual(payload["message"], "DNS record sync failed")
        self.assertEqual(payload["details"]["dns_failed"], True)
        self.assertIn("timestamp", payload)

    @patch("httpx.Client")
    def test_cooldown_throttling(self, mock_client_cls):
        """Verify identical alerts are throttled within cooldown window."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        dispatcher = NotificationDispatcher(
            webhook_url="https://example.com/webhook",
            cooldown_seconds=60.0,
        )

        # First alert - passes through
        success, msg = dispatcher.dispatch_sync("TEST_ALERT", "Test Title", "Message 1")
        self.assertTrue(success)
        self.assertEqual(mock_client.post.call_count, 1)

        # Second identical alert - throttled
        success, msg = dispatcher.dispatch_sync("TEST_ALERT", "Test Title", "Message 2")
        self.assertFalse(success)
        self.assertIn("throttled", msg.lower())
        self.assertEqual(mock_client.post.call_count, 1)

        # Different alert - passes through
        success, msg = dispatcher.dispatch_sync("OTHER_ALERT", "Other Title", "Message 3")
        self.assertTrue(success)
        self.assertEqual(mock_client.post.call_count, 2)

    @patch("httpx.Client")
    def test_webhook_error_does_not_raise(self, mock_client_cls):
        """Verify network errors or HTTP errors are caught gracefully and return False."""
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        dispatcher = NotificationDispatcher(webhook_url="https://example.com/webhook")
        success, msg = dispatcher.dispatch_sync("TEST_ALERT", "Test Title", "Message")

        self.assertFalse(success)
        self.assertIn("Connection refused", msg)


if __name__ == "__main__":
    unittest.main()
