import unittest
from unittest.mock import patch, MagicMock
import os
import time
import app


class TestDNSTombstoningAndGracePeriod(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["docker_connected"] = True
        app.sync_state["discovered_services"] = []
        app.sync_state["all_containers"] = []
        app.sync_state["dns_records"] = []
        app.sync_state["logs"] = []
        app.sync_state["tombstones"] = {}

    @patch("builtins.open", MagicMock())
    @patch("os.makedirs", MagicMock())
    @patch("app.cf_api")
    @patch("app.docker_api", return_value=[])
    @patch("app.get_docker_containers")
    def test_missing_container_gets_tombstoned_and_not_deleted(self, mock_get_containers, mock_docker_api, mock_cf_api):
        """Verify that when a container stops, its DNS record is tombstoned and NOT deleted within grace period."""
        mock_get_containers.return_value = ([], [])

        def fake_cf_api(endpoint, token, method="GET", data=None, **kwargs):
            if "/zones?" in endpoint:
                return {"result": [{"id": "zone-123", "account": {"id": "fake-acc"}}]}
            if "cfd_tunnel?" in endpoint:
                return {"result": [{"id": "tun-123", "name": "fake-tunnel"}]}
            if "/dns_records?type=CNAME&content=" in endpoint:
                return {"result": [{"id": "rec-1", "name": "app.example.com", "content": "tun-123.cfargotunnel.com"}]}
            if "/dns_records?type=CNAME&name=" in endpoint:
                return {"result": []}
            return {"result": {}}

        mock_cf_api.side_effect = fake_cf_api

        with patch.dict(os.environ, {
            "CLOUDFLARE_API_TOKEN": "fake-token",
            "CLOUDFLARE_ACCOUNT_ID": "fake-acc",
            "CLOUDFLARE_ZONE_ID": "zone-123",
            "CLOUDFLARE_TUNNEL_NAME": "fake-tunnel",
            "DOMAIN_NAME": "example.com",
            "DNS_CLEANUP_GRACE_PERIOD": "300"
        }):
            app.run_sync_logic()

        self.assertIn("app.example.com", app.sync_state["tombstones"])
        delete_calls = [call for call in mock_cf_api.call_args_list if call.kwargs.get("method") == "DELETE"]
        self.assertEqual(len(delete_calls), 0)
        self.assertTrue(any("Tombstoned app.example.com" in log for log in app.sync_state["logs"]))

    @patch("builtins.open", MagicMock())
    @patch("os.makedirs", MagicMock())
    @patch("app.cf_api")
    @patch("app.docker_api", return_value=[])
    @patch("app.get_docker_containers")
    def test_container_recovery_clears_tombstone(self, mock_get_containers, mock_docker_api, mock_cf_api):
        """Verify that when a container recovers before grace period, its tombstone is cleared."""
        app.sync_state["tombstones"]["app.example.com"] = time.time() - 50

        mock_get_containers.return_value = ([
            {"container": "app", "hostname": "app.example.com", "service": "http://app:80", "originRequest": {}}
        ], [])

        def fake_cf_api(endpoint, token, method="GET", data=None, **kwargs):
            if "/zones?" in endpoint:
                return {"result": [{"id": "zone-123", "account": {"id": "fake-acc"}}]}
            if "cfd_tunnel?" in endpoint:
                return {"result": [{"id": "tun-123", "name": "fake-tunnel"}]}
            if "/dns_records?type=CNAME&name=app.example.com" in endpoint:
                return {"result": [{"id": "rec-1", "name": "app.example.com", "content": "tun-123.cfargotunnel.com", "proxied": True}]}
            if "/dns_records?type=CNAME&content=" in endpoint:
                return {"result": [{"id": "rec-1", "name": "app.example.com", "content": "tun-123.cfargotunnel.com"}]}
            return {"result": {}}

        mock_cf_api.side_effect = fake_cf_api

        with patch.dict(os.environ, {
            "CLOUDFLARE_API_TOKEN": "fake-token",
            "CLOUDFLARE_ACCOUNT_ID": "fake-acc",
            "CLOUDFLARE_ZONE_ID": "zone-123",
            "CLOUDFLARE_TUNNEL_NAME": "fake-tunnel",
            "DOMAIN_NAME": "example.com",
            "DNS_CLEANUP_GRACE_PERIOD": "300"
        }):
            app.run_sync_logic()

        self.assertNotIn("app.example.com", app.sync_state["tombstones"])
        self.assertTrue(any("Container recovered for app.example.com" in log for log in app.sync_state["logs"]))

    @patch("builtins.open", MagicMock())
    @patch("os.makedirs", MagicMock())
    @patch("app.cf_api")
    @patch("app.docker_api", return_value=[])
    @patch("app.get_docker_containers")
    def test_tombstone_expiry_deletes_dns_record(self, mock_get_containers, mock_docker_api, mock_cf_api):
        """Verify that after grace period elapses, the obsolete DNS record is deleted."""
        app.sync_state["tombstones"]["old.example.com"] = time.time() - 350
        mock_get_containers.return_value = ([], [])

        def fake_cf_api(endpoint, token, method="GET", data=None, **kwargs):
            if "/zones?" in endpoint:
                return {"result": [{"id": "zone-123", "account": {"id": "fake-acc"}}]}
            if "cfd_tunnel?" in endpoint:
                return {"result": [{"id": "tun-123", "name": "fake-tunnel"}]}
            if "/dns_records?type=CNAME&content=" in endpoint:
                return {"result": [{"id": "rec-99", "name": "old.example.com", "content": "tun-123.cfargotunnel.com"}]}
            return {"result": {}}

        mock_cf_api.side_effect = fake_cf_api

        with patch.dict(os.environ, {
            "CLOUDFLARE_API_TOKEN": "fake-token",
            "CLOUDFLARE_ACCOUNT_ID": "fake-acc",
            "CLOUDFLARE_ZONE_ID": "zone-123",
            "CLOUDFLARE_TUNNEL_NAME": "fake-tunnel",
            "DOMAIN_NAME": "example.com",
            "DNS_CLEANUP_GRACE_PERIOD": "300"
        }):
            app.run_sync_logic()

        delete_calls = [call for call in mock_cf_api.call_args_list if call.kwargs.get("method") == "DELETE"]
        self.assertEqual(len(delete_calls), 1)
        self.assertIn("rec-99", delete_calls[0].args[0])
        self.assertNotIn("old.example.com", app.sync_state["tombstones"])
        self.assertTrue(any("after grace period expired" in log for log in app.sync_state["logs"]))

    @patch("builtins.open", MagicMock())
    @patch("os.makedirs", MagicMock())
    @patch("app.cf_api")
    @patch("app.docker_api", return_value=[])
    @patch("app.get_docker_containers")
    def test_immediate_cleanup_bypasses_grace_period(self, mock_get_containers, mock_docker_api, mock_cf_api):
        """Verify that DNS_IMMEDIATE_CLEANUP=true deletes records immediately without tombstoning."""
        mock_get_containers.return_value = ([], [])

        def fake_cf_api(endpoint, token, method="GET", data=None, **kwargs):
            if "/zones?" in endpoint:
                return {"result": [{"id": "zone-123", "account": {"id": "fake-acc"}}]}
            if "cfd_tunnel?" in endpoint:
                return {"result": [{"id": "tun-123", "name": "fake-tunnel"}]}
            if "/dns_records?type=CNAME&content=" in endpoint:
                return {"result": [{"id": "rec-fast", "name": "fast.example.com", "content": "tun-123.cfargotunnel.com"}]}
            return {"result": {}}

        mock_cf_api.side_effect = fake_cf_api

        with patch.dict(os.environ, {
            "CLOUDFLARE_API_TOKEN": "fake-token",
            "CLOUDFLARE_ACCOUNT_ID": "fake-acc",
            "CLOUDFLARE_ZONE_ID": "zone-123",
            "CLOUDFLARE_TUNNEL_NAME": "fake-tunnel",
            "DOMAIN_NAME": "example.com",
            "DNS_IMMEDIATE_CLEANUP": "true"
        }):
            app.run_sync_logic()

        delete_calls = [call for call in mock_cf_api.call_args_list if call.kwargs.get("method") == "DELETE"]
        self.assertEqual(len(delete_calls), 1)
        self.assertIn("rec-fast", delete_calls[0].args[0])
        self.assertEqual(len(app.sync_state["tombstones"]), 0)


if __name__ == "__main__":
    unittest.main()
