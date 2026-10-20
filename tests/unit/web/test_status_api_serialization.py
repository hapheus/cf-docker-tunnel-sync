import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


class TestStatusApiSerialization(unittest.TestCase):
    def setUp(self):
        # Reset sync state
        app.sync_state["status"] = "Active / Synced"
        app.sync_state["logs"] = []
        app.sync_state["discovered_services"] = []
        app.sync_state["all_containers"] = []
        app.sync_state["dns_records"] = []
        app.sync_state["tombstones"] = {}
        app.sync_state["_deprecations_warned"] = set()
        if "_last_ingress" in app.sync_state:
            del app.sync_state["_last_ingress"]
        self.client = TestClient(app.app)

    @patch("app.docker_api")
    def test_tc_41_01_canonical_labels_serialization(self, mock_docker):
        """TC-41-01: Baseline Canonical Labels - Clean API Serialization."""
        mock_docker.return_value = [
            {
                "Id": "c101",
                "Names": ["/canonical-svc"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.hostname": "app.example.com",
                    "cf.tunnel.port": "8080",
                },
            }
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
            app.get_docker_containers()

        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp.headers.get("content-type", ""))
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("tunnel_name", data)
        self.assertNotIn("_deprecations_warned", data)

    @patch("app.docker_api")
    def test_tc_41_02_legacy_labels_set_serialization(self, mock_docker):
        """TC-41-02: Legacy cloudflared.* Labels - Set Deserialization Resilience."""
        mock_docker.return_value = [
            {
                "Id": "c102",
                "Names": ["/legacy-svc"],
                "State": "running",
                "Labels": {
                    "cloudflared.hostname": "legacy.example.com",
                    "cloudflared.port": "8080",
                },
            }
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
            app.get_docker_containers()

        # Ensure _deprecations_warned has populated elements
        self.assertGreater(len(app.sync_state.get("_deprecations_warned", set())), 0)

        # GET /api/status must not throw 500 or TypeError
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn("_deprecations_warned", data)
        self.assertTrue(any("Deprecation Notice" in log for log in data.get("logs", [])))

    @patch("app.docker_api")
    def test_tc_41_03_bare_shorthand_multiple_deprecations(self, mock_docker):
        """TC-41-03: Bare Shorthand Labels - Multiple Deprecations."""
        mock_docker.return_value = [
            {
                "Id": "c103",
                "Names": ["/shorthand-svc"],
                "State": "running",
                "Labels": {
                    "hostname": "short.example.com",
                    "port": "3000",
                    "proto": "http",
                    "notlsverify": "true",
                },
            }
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
            app.get_docker_containers()

        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn("_deprecations_warned", data)
        self.assertEqual(data["status"], "Active / Synced")

    @patch("app.docker_api")
    def test_tc_41_04_repeated_discovery_multi_cycle(self, mock_docker):
        """TC-41-04: Repeated Discovery & Multi-Container Sync Cycles."""
        mock_docker.return_value = [
            {
                "Id": "c104a",
                "Names": ["/canon-svc"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "a.example.com", "cf.tunnel.port": "80"},
            },
            {
                "Id": "c104b",
                "Names": ["/legacy-svc"],
                "State": "running",
                "Labels": {"cloudflared.hostname": "b.example.com", "cloudflared.port": "81"},
            },
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}):
            # Multiple cycles
            app.get_docker_containers()
            app.get_docker_containers()

        resp1 = self.client.get("/api/status")
        self.assertEqual(resp1.status_code, 200)
        resp2 = self.client.get("/api/status")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp1.json(), resp2.json())

    @patch("app.run_sync_logic")
    def test_api_sync_endpoint_serialization(self, mock_sync):
        """Verify /api/sync endpoint safely sanitizes state without 500 error."""
        app.sync_state["_deprecations_warned"] = {("c1", "port")}
        resp = self.client.post("/api/sync")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("message"), "Sync triggered")
        self.assertNotIn("_deprecations_warned", data.get("state", {}))

    def test_tc_41_05_private_state_filtering_and_nested_sanitization(self):
        """TC-41-05: Private State Key Filtering (_*) & Nested Non-Primitive Sanitization."""
        # Inject private keys and complex types into sync_state
        app.sync_state["_deprecations_warned"] = {("c1", "port"), ("c2", "proto")}
        app.sync_state["_last_ingress"] = [{"hostname": "a.example.com", "service": "http://a:80"}]
        app.sync_state["_internal_set"] = {"item1", "item2"}
        app.sync_state["discovered_services"] = [{"hostname": "a.example.com", "tags": {"tag1", "tag2"}}]

        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Verify no keys starting with '_' leaked
        for key in list(data.keys()):
            self.assertFalse(key.startswith("_"), f"Private key '{key}' found in /api/status response")

        # Verify nested sets were sanitized to serializable lists
        discovered = data.get("discovered_services", [])
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0]["tags"], ["tag1", "tag2"])


if __name__ == "__main__":
    unittest.main()
