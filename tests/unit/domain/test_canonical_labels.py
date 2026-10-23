import os
import unittest
from unittest.mock import patch

import app


class TestCanonicalLabelsAndDeprecation(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["logs"] = []
        app.sync_state["_deprecations_warned"] = set()

    @patch("app.docker_api")
    def test_canonical_labels_no_deprecation_warnings(self, mock_docker_api):
        """Verify 100% canonical labels parse without triggering deprecation warnings."""
        mock_docker_api.return_value = [
            {
                "Names": ["/canonical-service"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.hostname": "api.example.com",
                    "cf.tunnel.port": "8080",
                    "cf.tunnel.protocol": "http",
                },
            }
        ]

        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
            services, _ = app.get_docker_containers()

        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["hostname"], "api.example.com")
        self.assertFalse(any("Deprecation Notice" in log for log in app.sync_state["logs"]))

    @patch("app.docker_api")
    def test_legacy_labels_trigger_deprecation_warning_once(self, mock_docker_api):
        """Verify legacy cloudflared.* and shorthand labels trigger a deprecation warning cleanly once."""
        mock_docker_api.return_value = [
            {
                "Names": ["/legacy-service"],
                "State": "running",
                "Labels": {
                    "cloudflared.hostname": "legacy.example.com",
                    "cloudflared.port": "5000",
                    "proto": "https",
                    "notlsverify": "true",
                },
            }
        ]

        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
            # First sync run
            services, _ = app.get_docker_containers()
            deprecation_logs_1 = [entry for entry in app.sync_state["logs"] if "Deprecation Notice" in entry]

            # Second sync run with identical container
            app.get_docker_containers()
            deprecation_logs_2 = [entry for entry in app.sync_state["logs"] if "Deprecation Notice" in entry]

        # Verified service was parsed correctly with backward compatibility
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["hostname"], "legacy.example.com")
        self.assertEqual(services[0]["service"], "https://legacy-service:5000")
        self.assertTrue(services[0]["no_tls_verify"])

        # Warnings were emitted on first run
        self.assertGreater(len(deprecation_logs_1), 0)
        self.assertTrue(any("cloudflared.hostname" in entry for entry in deprecation_logs_1))
        self.assertTrue(any("proto" in entry for entry in deprecation_logs_1))

        # Warnings were NOT duplicated on second run
        self.assertEqual(len(deprecation_logs_1), len(deprecation_logs_2))

    def test_has_tunnel_labels_detection(self):
        """Verify has_tunnel_labels correctly identifies tunnel-relevant labels and ignores others."""
        from tunnel_sync.domain.labels import has_tunnel_labels

        # Modern cf.tunnel labels
        self.assertTrue(has_tunnel_labels({"cf.tunnel.hostname": "app.example.com"}))
        self.assertTrue(has_tunnel_labels({"cf.tunnel.port": "8080"}))
        self.assertTrue(has_tunnel_labels({"cf.tunnel.enable": "true"}))

        # Legacy and shorthand prefixes
        self.assertTrue(has_tunnel_labels({"cloudflared.hostname": "app.example.com"}))
        self.assertTrue(has_tunnel_labels({"cftunnel.domain": "app.example.com"}))
        self.assertTrue(has_tunnel_labels({"tunnel.hostname": "app.example.com"}))

        # Shorthand exact labels
        self.assertTrue(has_tunnel_labels({"hostname": "app.example.com"}))
        self.assertTrue(has_tunnel_labels({"port": "3000"}))
        self.assertTrue(has_tunnel_labels({"proto": "https"}))

        # Unrelated labels
        self.assertFalse(has_tunnel_labels({}))
        self.assertFalse(has_tunnel_labels({"com.docker.compose.project": "my-stack"}))
        self.assertFalse(has_tunnel_labels({"traefik.enable": "true", "traefik.http.routers.app.rule": "Host(`...`)"}))
        self.assertFalse(has_tunnel_labels({"org.opencontainers.image.version": "1.0"}))
        self.assertFalse(has_tunnel_labels({"name": "postgres"}))


if __name__ == "__main__":
    unittest.main()
