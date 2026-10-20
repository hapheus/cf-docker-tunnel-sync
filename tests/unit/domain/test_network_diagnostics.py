import os
import unittest
from unittest.mock import patch

import app


class TestDockerNetworkDiagnostics(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["logs"] = []
        app.sync_state["_deprecations_warned"] = set()

    @patch("app.docker_api")
    def test_shared_network_container_is_valid_and_connected(self, mock_docker_api):
        """Verify container sharing CF_NETWORK_NAME is marked network_connected=True without warnings."""
        mock_docker_api.return_value = [
            {
                "Names": ["/my-web"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "web.example.com", "cf.tunnel.port": "80"},
                "NetworkSettings": {"Networks": {"cf-tunnel-net": {}}},
            }
        ]

        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com", "CF_NETWORK_NAME": "cf-tunnel-net"}):
            services, all_c = app.get_docker_containers()

        self.assertEqual(len(services), 1)
        self.assertTrue(services[0]["network_connected"])
        self.assertNotIn("network_warning", services[0])
        self.assertTrue(all_c[0]["network_connected"])

    @patch("app.docker_api")
    def test_isolated_network_container_triggers_warning(self, mock_docker_api):
        """Verify container on an isolated network triggers a pre-flight warning preventing silent 502."""
        mock_docker_api.return_value = [
            {
                "Names": ["/isolated-service"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "isolated.example.com", "cf.tunnel.port": "8080"},
                "NetworkSettings": {"Networks": {"private-db-net": {}}},
            }
        ]

        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com", "CF_NETWORK_NAME": "cf-tunnel-net"}):
            services, all_c = app.get_docker_containers()

        self.assertEqual(len(services), 1)
        self.assertFalse(services[0]["network_connected"])
        self.assertIn("network_warning", services[0])
        self.assertIn("Missing shared network", services[0]["network_warning"])
        self.assertFalse(all_c[0]["network_connected"])
        self.assertTrue(any("502 Bad Gateway" in log for log in app.sync_state["logs"]))

    @patch("app.docker_api")
    def test_strict_mode_excludes_disconnected_container(self, mock_docker_api):
        """Verify REQUIRE_SHARED_NETWORK=true excludes disconnected containers from ingress sync."""
        mock_docker_api.return_value = [
            {
                "Names": ["/isolated-service"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "isolated.example.com", "cf.tunnel.port": "8080"},
                "NetworkSettings": {"Networks": {"isolated-net": {}}},
            }
        ]

        with patch.dict(
            os.environ,
            {"DOMAIN_NAME": "example.com", "CF_NETWORK_NAME": "cf-tunnel-net", "REQUIRE_SHARED_NETWORK": "true"},
        ):
            services, all_c = app.get_docker_containers()

        # Excluded from services
        self.assertEqual(len(services), 0)
        self.assertEqual(len(all_c), 1)
        self.assertFalse(all_c[0]["is_tunneled"])
        self.assertFalse(all_c[0]["network_connected"])
        self.assertTrue(any("REQUIRE_SHARED_NETWORK=true" in log for log in app.sync_state["logs"]))

    @patch("app.docker_api")
    def test_dynamic_cloudflared_network_matching(self, mock_docker_api):
        """Verify containers sharing dynamic networks discovered on cloudflared container are recognized."""
        mock_docker_api.return_value = [
            {
                "Names": ["/my-cloudflared"],
                "State": "running",
                "Labels": {"com.docker.compose.service": "cloudflared"},
                "NetworkSettings": {"Networks": {"custom-app-network": {}}},
            },
            {
                "Names": ["/my-app"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "app.example.com", "cf.tunnel.port": "3000"},
                "NetworkSettings": {"Networks": {"custom-app-network": {}}},
            },
        ]

        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com", "CF_NETWORK_NAME": "cf-tunnel-net"}):
            services, all_c = app.get_docker_containers()

        self.assertEqual(len(services), 1)
        self.assertTrue(services[0]["network_connected"])


if __name__ == "__main__":
    unittest.main()
