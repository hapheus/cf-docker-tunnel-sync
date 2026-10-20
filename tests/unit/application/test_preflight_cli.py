import os
import unittest
from unittest.mock import patch

import app
from diagnostics import mask_sensitive_text
from tests.paths import REPO_ROOT


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
        root_dir = str(REPO_ROOT)
        quickstart_path = os.path.join(root_dir, "QUICKSTART.md")
        self.assertTrue(os.path.isfile(quickstart_path), "QUICKSTART.md must exist in root repository")

        with open(quickstart_path, "r") as f:
            content = f.read()

        self.assertIn("cf-tunnel-sync", content)
        self.assertIn("cloudflared", content)
        self.assertIn("--preflight", content)
        self.assertIn("cf.tunnel.hostname", content)
        self.assertIn("cf.tunnel.port", content)

    def test_preflight_structured_diagnostics_format(self):
        """Verifies that failure outputs include What failed, Why, and How to fix (Issue #97)."""
        with patch.dict(
            os.environ,
            {"CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_TOKEN": "", "DOMAIN_NAME": "example.com"},
            clear=True,
        ):
            with patch("app.docker_api", return_value={"Version": "26.1.0"}):
                with self.assertLogs("cf-tunnel-sync", level="ERROR") as cm:
                    code = app.run_preflight_validation()

                self.assertEqual(code, 1)
                log_text = "\n".join(cm.output)
                self.assertIn("❌ [PREFLIGHT FAIL]", log_text)
                self.assertIn("• What failed:", log_text)
                self.assertIn("• Why:", log_text)
                self.assertIn("• How to fix:", log_text)

    def test_preflight_zero_secrets_printed_in_logs(self):
        """Verifies that raw secret tokens are never printed in preflight logs (Issue #97)."""
        secret_token = "secret-super-confidential-token-1234567890"

        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_API_TOKEN": secret_token,
                "DOMAIN_NAME": "example.com",
            },
        ):
            with patch("app.docker_api", return_value={"Version": "26.1.0"}):
                with patch("app.cf_api") as mock_cf:
                    # Simulate an exception containing the secret token in the message
                    mock_cf.side_effect = RuntimeError(f"Connection to api.cloudflare.com failed with {secret_token}")

                    with self.assertLogs("cf-tunnel-sync", level="ERROR") as cm:
                        code = app.run_preflight_validation()

                    self.assertEqual(code, 1)
                    log_text = "\n".join(cm.output)
                    self.assertNotIn(secret_token, log_text, "Secret token MUST be masked in preflight logs")
                    self.assertIn("[MASKED]", log_text, "Masked placeholder must replace secret")

    def test_mask_sensitive_text_utility(self):
        """Verifies the mask_sensitive_text helper masks tokens, authorization headers, and custom secrets."""
        raw_text = "Error Authorization: Bearer secret_bearer_token_xyz987654321 with token=my_secret_token_12345678"
        masked = mask_sensitive_text(raw_text, extra_secrets=["my_secret_token_12345678"])
        self.assertNotIn("secret_bearer_token_xyz987654321", masked)
        self.assertNotIn("my_secret_token_12345678", masked)
        self.assertIn("[MASKED]", masked)


if __name__ == "__main__":
    unittest.main()
