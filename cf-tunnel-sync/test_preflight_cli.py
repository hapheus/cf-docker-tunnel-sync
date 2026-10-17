import os
import unittest
from unittest.mock import patch

import app


class TestPreflightValidationMode(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["logs"] = []
        app.sync_state["docker_connected"] = True

    @patch("app.get_docker_containers")
    @patch("app.cf_api")
    @patch("app.docker_api")
    def test_preflight_success_non_mutating(self, mock_docker_api, mock_cf_api, mock_get_containers):
        """Hermetically verifies that preflight succeeds (exits 0) on valid environment

        and invokes ONLY read-only (GET) queries, never mutator methods (POST, PUT, DELETE, PATCH).
        """
        mock_docker_api.return_value = {"Version": "26.1.0"}
        mock_get_containers.return_value = ([], [])

        def cf_side_effect(endpoint, token, method="GET", data=None, **kwargs):
            # Assert non-mutating guarantee: method must strictly be GET
            self.assertEqual(method.upper(), "GET", f"Preflight illegally called mutating method: {method}")
            self.assertIsNone(data, f"Preflight illegally provided mutation data: {data}")

            if "/user/tokens/verify" in endpoint:
                return {"result": {"status": "active"}}
            if "/zones?name=" in endpoint:
                return {"result": [{"id": "zone-xyz-123", "account": {"id": "acc-abc-456"}}]}
            if "/cfd_tunnel" in endpoint:
                return {"result": [{"id": "tun-789", "name": "cf-docker-tunnel-sync"}]}
            return {"result": []}

        mock_cf_api.side_effect = cf_side_effect

        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_API_TOKEN": "valid-test-token",
                "DOMAIN_NAME": "example.com",
                "CLOUDFLARE_TUNNEL_NAME": "cf-docker-tunnel-sync",
            },
        ):
            code = app.run_preflight_validation()

        self.assertEqual(code, 0, "Preflight should exit 0 on valid environment")
        self.assertTrue(mock_docker_api.called)
        self.assertTrue(mock_cf_api.called)

        # Verify all CF API calls were strictly GET
        for call_args in mock_cf_api.call_args_list:
            method_used = call_args.kwargs.get("method", "GET")
            self.assertEqual(method_used.upper(), "GET")

    @patch("app.docker_api")
    def test_preflight_fails_when_docker_unreachable(self, mock_docker_api):
        """Preflight exits non-zero with actionable remedy message when Docker socket fails."""
        mock_docker_api.side_effect = RuntimeError("Permission denied accessing /var/run/docker.sock")

        with patch.dict(
            os.environ,
            {"CLOUDFLARE_API_TOKEN": "valid-token", "DOMAIN_NAME": "example.com"},
        ):
            code = app.run_preflight_validation()

        self.assertNotEqual(code, 0, "Preflight must exit non-zero when Docker is unreachable")

    def test_preflight_fails_when_token_missing(self):
        """Preflight exits non-zero with remedy message when CLOUDFLARE_API_TOKEN is missing."""
        with patch.dict(
            os.environ,
            {"CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_TOKEN": "", "DOMAIN_NAME": "example.com"},
            clear=True,
        ):
            with patch("app.docker_api", return_value={"Version": "26.1.0"}):
                code = app.run_preflight_validation()

        self.assertNotEqual(code, 0, "Preflight must exit non-zero when token is missing")

    @patch("app.cf_api")
    @patch("app.docker_api")
    def test_preflight_fails_when_tunnel_missing(self, mock_docker_api, mock_cf_api):
        """Preflight exits non-zero with actionable remedy when Cloudflare Tunnel does not exist."""
        mock_docker_api.return_value = {"Version": "26.1.0"}

        def cf_side_effect(endpoint, token, method="GET", data=None, **kwargs):
            if "/user/tokens/verify" in endpoint:
                return {"result": {"status": "active"}}
            if "/zones?name=" in endpoint:
                return {"result": [{"id": "zone-123", "account": {"id": "acc-123"}}]}
            if "/cfd_tunnel" in endpoint:
                # Return empty list -> tunnel does not exist
                return {"result": []}
            return {"result": []}

        mock_cf_api.side_effect = cf_side_effect

        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_API_TOKEN": "test-token",
                "DOMAIN_NAME": "example.com",
                "CLOUDFLARE_TUNNEL_NAME": "non-existent-tunnel",
            },
        ):
            code = app.run_preflight_validation()

        self.assertNotEqual(code, 0, "Preflight must exit non-zero when tunnel does not exist")

    def test_quickstart_markdown_exists_and_contains_compose(self):
        """Verifies that QUICKSTART.md is present and contains valid compose definition."""
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        quickstart_path = os.path.join(root_dir, "QUICKSTART.md")
        self.assertTrue(os.path.isfile(quickstart_path), "QUICKSTART.md must exist in root repository")

        with open(quickstart_path, "r") as f:
            content = f.read()

        self.assertIn("cf-tunnel-sync", content)
        self.assertIn("cloudflared", content)
        self.assertIn("--preflight", content)
        self.assertIn("cf.tunnel.hostname", content)
        self.assertIn("cf.tunnel.port", content)


if __name__ == "__main__":
    unittest.main()
