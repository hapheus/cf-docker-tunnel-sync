import unittest
from unittest.mock import patch, MagicMock
import urllib.error
import io
import os
import app

class TestAppSyncLogic(unittest.TestCase):
    def setUp(self):
        # Reset sync_state
        app.sync_state["status"] = "Initializing"
        app.sync_state["tunnel_id"] = None
        app.sync_state["discovered_services"] = []
        app.sync_state["all_containers"] = []
        app.sync_state["dns_records"] = []
        app.sync_state["logs"] = []
        if "_last_ingress" in app.sync_state:
            del app.sync_state["_last_ingress"]

    @patch("app.cf_api")
    @patch("app.get_docker_containers")
    @patch("app.docker_api")
    @patch("os.path.exists", return_value=True)
    @patch("os.makedirs", MagicMock())
    @patch("builtins.open", MagicMock())
    def test_sync_resolves_account_id_from_zone_when_accounts_empty(
        self, mock_exists, mock_docker_api, mock_get_containers, mock_cf_api
    ):
        """Test that account_id is extracted from zone when /accounts returns empty list"""
        mock_get_containers.return_value = ([], [])

        def fake_cf_api(endpoint, token, method="GET", data=None):
            if endpoint == "/accounts":
                return {"result": []}
            if endpoint.startswith("/zones?name="):
                return {
                    "result": [
                        {
                            "id": "zone-123",
                            "name": "example.com",
                            "account": {"id": "acc-from-zone", "name": "My Account"},
                        }
                    ]
                }
            if "/cfd_tunnel?name=" in endpoint:
                return {"result": [{"id": "tun-123", "name": "my-tunnel"}]}
            if "/token" in endpoint:
                return {"result": "fake-token"}
            if "/configurations" in endpoint:
                return {"result": {}}
            if "/dns_records" in endpoint:
                return {"result": []}
            return {"result": []}

        mock_cf_api.side_effect = fake_cf_api

        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_API_TOKEN": "valid-token",
                "DOMAIN_NAME": "example.com",
                "CLOUDFLARE_TUNNEL_NAME": "my-tunnel",
            },
            clear=True,
        ):
            app.run_sync_logic()

        self.assertNotEqual(
            app.sync_state["status"],
            "Error: No Account",
            "Sync should not fail with 'Error: No Account' when zone provides account ID",
        )
        self.assertEqual(app.sync_state["status"], "Active / Synced")
        self.assertEqual(app.sync_state["tunnel_id"], "tun-123")

    @patch("app.cf_api")
    @patch("app.get_docker_containers")
    @patch("app.docker_api")
    @patch("os.path.exists", return_value=True)
    @patch("os.makedirs", MagicMock())
    @patch("builtins.open", MagicMock())
    def test_sync_idempotency_ingress_and_dns(
        self, mock_exists, mock_docker_api, mock_get_containers, mock_cf_api
    ):
        """Test that unchanged ingress and unchanged DNS do not trigger redundant PUT calls on next sync"""
        service = [{"container": "web", "hostname": "web.example.com", "service": "http://web:80"}]
        mock_get_containers.return_value = (service, [{"name": "web", "state": "running", "hostname": "web.example.com", "is_tunneled": True}])

        put_calls = []

        def fake_cf_api(endpoint, token, method="GET", data=None):
            if method == "PUT":
                put_calls.append((endpoint, data))
            if endpoint.startswith("/zones?name="):
                return {
                    "result": [
                        {
                            "id": "zone-123",
                            "name": "example.com",
                            "account": {"id": "acc-123", "name": "My Account"},
                        }
                    ]
                }
            if "/cfd_tunnel?name=" in endpoint:
                return {"result": [{"id": "tun-123", "name": "my-tunnel"}]}
            if "/token" in endpoint:
                return {"result": "fake-token"}
            if "/configurations" in endpoint:
                return {"result": {}}
            if "/dns_records?type=CNAME&name=web.example.com" in endpoint:
                # Existing record already matches target CNAME and proxied
                return {
                    "result": [
                        {
                            "id": "rec-1",
                            "name": "web.example.com",
                            "content": "tun-123.cfargotunnel.com",
                            "proxied": True,
                        }
                    ]
                }
            if "/dns_records?type=CNAME&content=" in endpoint:
                return {"result": [{"id": "rec-1", "name": "web.example.com"}]}
            return {"result": []}

        mock_cf_api.side_effect = fake_cf_api

        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_API_TOKEN": "valid-token",
                "DOMAIN_NAME": "example.com",
                "CLOUDFLARE_TUNNEL_NAME": "my-tunnel",
            },
            clear=True,
        ):
            # First sync: ingress rules will be configured
            app.run_sync_logic()
            initial_puts = len(put_calls)
            self.assertEqual(initial_puts, 1, "Only ingress PUT should be called (DNS already matches)")

            # Second sync with identical services
            app.run_sync_logic()
            self.assertEqual(len(put_calls), initial_puts, "No additional PUT calls should occur when state is identical")

    def test_no_hardcoded_domain_fallback(self):
        """DOMAIN_NAME should not default to private domain 'fraha.dev'"""
        with patch.dict(os.environ, {}, clear=True):
            self.assertNotEqual(app.get_domain_name(), "fraha.dev")

    @patch("urllib.request.urlopen")
    def test_cf_api_error_formatting(self, mock_urlopen):
        """cf_api should parse Cloudflare error response body and format helpful message"""
        err_json = b'{"success": false, "errors": [{"code": 10000, "message": "Authentication error"}]}'
        fp = io.BytesIO(err_json)
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://api.cloudflare.com", 400, "Bad Request", {}, fp
        )
        with self.assertRaises(RuntimeError) as ctx:
            app.cf_api("/zones", "bad-token")
        self.assertIn("Authentication error", str(ctx.exception))
        self.assertIn("10000", str(ctx.exception))

    def test_health_endpoints(self):
        """Test that /health and /healthz endpoints return healthy status"""
        res = app.health()
        self.assertEqual(res["status"], "healthy")
        self.assertIn("sync_status", res)

    @patch("app.docker_api")
    def test_get_docker_containers_filters_by_domain(self, mock_docker_api):
        """Only containers matching DOMAIN_NAME should be included in discovered services"""
        mock_docker_api.return_value = [
            {
                "Names": ["/matching-subdomain"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "api.example.com", "cf.tunnel.port": "8000"},
            },
            {
                "Names": ["/matching-apex"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "example.com", "cf.tunnel.port": "80"},
            },
            {
                "Names": ["/other-domain"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "service.otherdomain.org", "cf.tunnel.port": "3000"},
            },
            {
                "Names": ["/false-suffix-domain"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "notexample.com", "cf.tunnel.port": "80"},
            },
        ]

        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}, clear=True):
            services, all_containers = app.get_docker_containers()

        service_hosts = [s["hostname"] for s in services]
        self.assertIn("api.example.com", service_hosts)
        self.assertIn("example.com", service_hosts)
        self.assertNotIn("service.otherdomain.org", service_hosts)
        self.assertNotIn("notexample.com", service_hosts)

    @patch("app.docker_api")
    def test_get_docker_containers_filters_by_tunnel_name_label(self, mock_docker_api):
        """If cf.tunnel.name label is set, only containers matching CLOUDFLARE_TUNNEL_NAME should be included"""
        mock_docker_api.return_value = [
            {
                "Names": ["/matching-tunnel"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.hostname": "app1.example.com",
                    "cf.tunnel.name": "tunnel-a",
                },
            },
            {
                "Names": ["/other-tunnel"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.hostname": "app2.example.com",
                    "cf.tunnel.name": "tunnel-b",
                },
            },
            {
                "Names": ["/no-tunnel-label"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.hostname": "app3.example.com",
                },
            },
        ]

        with patch.dict(
            os.environ,
            {"DOMAIN_NAME": "example.com", "CLOUDFLARE_TUNNEL_NAME": "tunnel-a"},
            clear=True,
        ):
            services, _ = app.get_docker_containers()

        service_hosts = [s["hostname"] for s in services]
        self.assertIn("app1.example.com", service_hosts)
        self.assertNotIn("app2.example.com", service_hosts)
        self.assertIn("app3.example.com", service_hosts)

    def test_find_cloudflared_container_name_with_env(self):
        """CLOUDFLARED_CONTAINER_NAME env var should override discovery"""
        with patch.dict(os.environ, {"CLOUDFLARED_CONTAINER_NAME": "my-custom-cf"}, clear=True):
            name = app.find_cloudflared_container_name()
            self.assertEqual(name, "my-custom-cf")

    @patch("app.docker_api")
    def test_find_cloudflared_container_name_auto_discovery(self, mock_docker_api):
        """Auto-discovers sibling cloudflared in the same Docker Compose project"""
        mock_docker_api.return_value = [
            {
                "Id": "sync123456789",
                "Names": ["/proj-a-cf-tunnel-sync-1"],
                "Labels": {
                    "com.docker.compose.project": "proj-a",
                    "com.docker.compose.service": "cf-tunnel-sync",
                },
            },
            {
                "Id": "cf123456789",
                "Names": ["/proj-a-cloudflared-1"],
                "Labels": {
                    "com.docker.compose.project": "proj-a",
                    "com.docker.compose.service": "cloudflared",
                },
            },
            {
                "Id": "cf987654321",
                "Names": ["/proj-b-cloudflared-1"],
                "Labels": {
                    "com.docker.compose.project": "proj-b",
                    "com.docker.compose.service": "cloudflared",
                },
            },
        ]

        with patch.dict(os.environ, {"HOSTNAME": "sync123456789"}, clear=True):
            name = app.find_cloudflared_container_name()
            self.assertEqual(name, "proj-a-cloudflared-1")

    @patch("app.docker_api")
    def test_find_cloudflared_container_name_fallback(self, mock_docker_api):
        """Falls back to 'cloudflared' if discovery yields no results"""
        mock_docker_api.return_value = []
        with patch.dict(os.environ, {}, clear=True):
            name = app.find_cloudflared_container_name()
            self.assertEqual(name, "cloudflared")

if __name__ == "__main__":
    unittest.main()

