"""Hermetic tests for declarative public vs protected access policy tagging (Issue #52 - R05)."""

import os
import unittest
from unittest.mock import patch

import app
from models import DiscoveredService
from starlette.testclient import TestClient


class TestAccessPolicyTagging(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        app.sync_state["services"] = []
        app.sync_state["discovered_services"] = []

    def test_default_unspecified_policy(self):
        """Unlabeled containers must default gracefully to 'unspecified' without breaking routing."""
        mock_containers = [
            {
                "Names": ["/web-app"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.hostname": "web.example.com",
                    "cf.tunnel.port": "80",
                },
            }
        ]

        with (
            patch("app.docker_api", return_value=mock_containers),
            patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}),
        ):
            services, all_c = app.get_docker_containers()
            self.assertEqual(len(services), 1)
            self.assertEqual(services[0]["access_policy"], "unspecified")
            self.assertEqual(all_c[0]["access_policy"], "unspecified")

    def test_explicit_policy_tags(self):
        """Verify parsing of public, protected, and internal policy tags."""
        test_cases = [
            ("cf.tunnel.access.policy", "public", "public"),
            ("cf.tunnel.access_policy", "protected", "protected"),
            ("cloudflared.access.policy", "internal", "internal"),
            ("cf.tunnel.access.policy", "  PROTECTED  ", "protected"),
            ("cf.tunnel.access.policy", "custom-tier", "custom-tier"),
        ]

        for label_key, label_val, expected in test_cases:
            mock_containers = [
                {
                    "Names": ["/policy-app"],
                    "State": "running",
                    "Labels": {
                        "cf.tunnel.hostname": "policy.example.com",
                        "cf.tunnel.port": "8080",
                        label_key: label_val,
                    },
                }
            ]

            with (
                patch("app.docker_api", return_value=mock_containers),
                patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}),
            ):
                services, _ = app.get_docker_containers()
                self.assertEqual(len(services), 1)
                self.assertEqual(services[0]["access_policy"], expected)

    def test_api_status_exposes_access_policy(self):
        """Verify /api/status endpoint includes access_policy in the service payload."""
        app.sync_state["services"] = [
            {
                "name": "vaultwarden",
                "hostname": "vault.example.com",
                "service": "http://vaultwarden:80",
                "access_policy": "protected",
                "status": "Active / Synced",
            },
            {
                "name": "blog",
                "hostname": "blog.example.com",
                "service": "http://blog:80",
                "access_policy": "public",
                "status": "Active / Synced",
            },
        ]

        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("services", data)
        self.assertEqual(data["services"][0]["access_policy"], "protected")
        self.assertEqual(data["services"][1]["access_policy"], "public")

    def test_discovered_service_model_validation(self):
        """Verify DiscoveredService Pydantic model defaults and validates access_policy field."""
        svc_default = DiscoveredService(
            container="app",
            hostname="app.example.com",
            service="http://app:80",
        )
        self.assertEqual(svc_default.access_policy, "unspecified")

        svc_explicit = DiscoveredService(
            container="app",
            hostname="app.example.com",
            service="http://app:80",
            access_policy="protected",
        )
        self.assertEqual(svc_explicit.access_policy, "protected")


if __name__ == "__main__":
    unittest.main()
