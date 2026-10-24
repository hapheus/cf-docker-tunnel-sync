"""
QA Test Specification & Acceptance Suite for cf-docker-tunnel-sync
Covers:
1. HTTPS / TLS origin service handling
2. noTLSVerify originRequest configuration & idempotency
3. Invalid / malformed Docker label resilience & sanitation
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import app


class TestTLSServiceAndLabels(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["tunnel_id"] = None
        app.sync_state["discovered_services"] = []
        app.sync_state["all_containers"] = []
        app.sync_state["dns_records"] = []
        app.sync_state["logs"] = []
        app.sync_state["_last_ingress"] = None

    # =========================================================================
    # Group 1: HTTPS / TLS Origins
    # =========================================================================

    @patch("app.docker_api")
    def test_explicit_https_service_url(self, mock_docker_api):
        """TC-TLS-01: Explicit https:// service URL must be preserved exactly."""
        mock_docker_api.return_value = [
            {
                "Names": ["/secure-vault"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "vault.example.com", "cf.tunnel.service": "https://secure-vault:8200"},
            }
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}, clear=True):
            services, _ = app.get_docker_containers()

        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["service"], "https://secure-vault:8200")
        self.assertEqual(services[0]["hostname"], "vault.example.com")

    @patch("app.docker_api")
    def test_proto_https_with_port(self, mock_docker_api):
        """TC-TLS-02: cf.tunnel.proto / cf.tunnel.scheme=https should construct https:// URL."""
        mock_docker_api.return_value = [
            {
                "Names": ["/internal-ssl"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.hostname": "ssl.example.com",
                    "cf.tunnel.port": "8443",
                    "cf.tunnel.proto": "https",
                },
            }
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}, clear=True):
            services, _ = app.get_docker_containers()

        self.assertEqual(len(services), 1)
        # Target expectation: when scheme/proto is https, service should start with https://
        self.assertTrue(
            services[0]["service"].startswith("https://"),
            f"Expected https:// origin service, got: {services[0]['service']}",
        )

    # =========================================================================
    # Group 2: noTLSVerify & originRequest Ingress Generation
    # =========================================================================

    @patch("app.docker_api")
    def test_notlsverify_label_extracted(self, mock_docker_api):
        """TC-NOTLS-01: cf.tunnel.notlsverify=true should be captured in service metadata."""
        mock_docker_api.return_value = [
            {
                "Names": ["/self-signed-service"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.hostname": "selfsigned.example.com",
                    "cf.tunnel.service": "https://self-signed-service:443",
                    "cf.tunnel.notlsverify": "true",
                },
            }
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}, clear=True):
            services, _ = app.get_docker_containers()

        self.assertEqual(len(services), 1)
        self.assertTrue(
            services[0].get("no_tls_verify") or services[0].get("noTLSVerify"),
            "Expected no_tls_verify flag to be true in discovered service",
        )

    @patch("app.cf_api")
    @patch("app.get_docker_containers")
    @patch("app.docker_api")
    @patch("os.makedirs", MagicMock())
    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=True)
    def test_sync_generates_origin_request_with_notlsverify(
        self, mock_exists, mock_docker_api, mock_get_containers, mock_cf_api
    ):
        """TC-NOTLS-02: Ingress rules sent to Cloudflare should include originRequest.noTLSVerify."""
        mock_get_containers.return_value = (
            [
                {
                    "container": "vault",
                    "hostname": "vault.example.com",
                    "service": "https://vault:8200",
                    "no_tls_verify": True,
                }
            ],
            [],
        )
        mock_docker_api.return_value = [{"Names": ["/cloudflared"], "State": "running"}]

        def fake_cf_api(endpoint, token, method="GET", data=None):
            if endpoint == "/accounts":
                return {"result": [{"id": "acc123"}]}
            if "/zones" in endpoint and "dns_records" not in endpoint:
                return {"result": [{"id": "zone123", "account": {"id": "acc123"}}]}
            if endpoint.startswith("/accounts/acc123/cfd_tunnel") and "/configurations" not in endpoint:
                return {"result": [{"id": "tun123", "name": "tunnel-a", "deleted_at": None}]}
            if "/token" in endpoint:
                return {"result": "fake-token"}
            if "/configurations" in endpoint:
                return {"result": {}}
            if "dns_records" in endpoint:
                return {"result": [{"id": "rec123", "name": "vault.example.com"}]}
            return {"result": []}

        mock_cf_api.side_effect = fake_cf_api

        env = {
            "CLOUDFLARE_API_TOKEN": "valid_token",
            "DOMAIN_NAME": "example.com",
            "CLOUDFLARE_TUNNEL_NAME": "tunnel-a",
        }
        with patch.dict(os.environ, env, clear=True):
            app.run_sync_logic()

        put_calls = [
            c for c in mock_cf_api.call_args_list if c[1].get("method") == "PUT" and "/configurations" in c[0][0]
        ]
        self.assertEqual(len(put_calls), 1)
        config_data = put_calls[0][1].get("data", {})
        ingress = config_data.get("config", {}).get("ingress", [])

        # Find vault rule
        vault_rule = next((r for r in ingress if r.get("hostname") == "vault.example.com"), None)
        self.assertIsNotNone(vault_rule)
        self.assertIn("originRequest", vault_rule)
        self.assertTrue(vault_rule["originRequest"].get("noTLSVerify"))

    @patch("app.cf_api")
    @patch("app.get_docker_containers")
    @patch("app.docker_api")
    @patch("os.makedirs", MagicMock())
    @patch("builtins.open", MagicMock())
    @patch("os.path.exists", return_value=True)
    def test_sync_no_origin_request_when_notlsverify_disabled(
        self, mock_exists, mock_docker_api, mock_get_containers, mock_cf_api
    ):
        """TC-NOTLS-03: Ingress rules without noTLSVerify should NOT have noTLSVerify: true."""
        mock_get_containers.return_value = (
            [
                {
                    "container": "plain-web",
                    "hostname": "web.example.com",
                    "service": "http://plain-web:80",
                    "no_tls_verify": False,
                }
            ],
            [],
        )
        mock_docker_api.return_value = [{"Names": ["/cloudflared"], "State": "running"}]

        def fake_cf_api(endpoint, token, method="GET", data=None):
            if endpoint == "/accounts":
                return {"result": [{"id": "acc123"}]}
            if "/zones" in endpoint and "dns_records" not in endpoint:
                return {"result": [{"id": "zone123", "account": {"id": "acc123"}}]}
            if endpoint.startswith("/accounts/acc123/cfd_tunnel") and "/configurations" not in endpoint:
                return {"result": [{"id": "tun123", "name": "tunnel-a", "deleted_at": None}]}
            if "/token" in endpoint:
                return {"result": "fake-token"}
            if "/configurations" in endpoint:
                return {"result": {}}
            if "dns_records" in endpoint:
                return {"result": [{"id": "rec123", "name": "web.example.com"}]}
            return {"result": []}

        mock_cf_api.side_effect = fake_cf_api

        env = {
            "CLOUDFLARE_API_TOKEN": "valid_token",
            "DOMAIN_NAME": "example.com",
            "CLOUDFLARE_TUNNEL_NAME": "tunnel-a",
        }
        with patch.dict(os.environ, env, clear=True):
            app.run_sync_logic()

        put_calls = [
            c for c in mock_cf_api.call_args_list if c[1].get("method") == "PUT" and "/configurations" in c[0][0]
        ]
        self.assertEqual(len(put_calls), 1)
        ingress = put_calls[0][1].get("data", {}).get("config", {}).get("ingress", [])
        web_rule = next((r for r in ingress if r.get("hostname") == "web.example.com"), None)
        self.assertIsNotNone(web_rule)
        # originRequest should either be absent or not have noTLSVerify: True
        if "originRequest" in web_rule:
            self.assertFalse(web_rule["originRequest"].get("noTLSVerify", False))

    # =========================================================================
    # Group 3: Invalid Label Handling & Edge Cases
    # =========================================================================

    @patch("app.docker_api")
    def test_invalid_port_non_numeric(self, mock_docker_api):
        """TC-INV-01: Non-numeric port string should not crash and should fall back safely."""
        mock_docker_api.return_value = [
            {
                "Names": ["/bad-port"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "badport.example.com", "cf.tunnel.port": "not-a-number"},
                "Ports": [{"PrivatePort": 8080}],
            }
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}, clear=True):
            services, _ = app.get_docker_containers()

        if services:
            self.assertNotIn("not-a-number", services[0]["service"])

    @patch("app.docker_api")
    def test_invalid_port_out_of_range(self, mock_docker_api):
        """TC-INV-02: Out-of-range port (e.g. 70000 or -1) must be rejected / normalized."""
        mock_docker_api.return_value = [
            {
                "Names": ["/out-of-range"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "range.example.com", "cf.tunnel.port": "99999"},
            }
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}, clear=True):
            services, _ = app.get_docker_containers()

        if services:
            self.assertNotIn("99999", services[0]["service"])

    @patch("app.docker_api")
    def test_hostname_with_mistaken_scheme(self, mock_docker_api):
        """TC-INV-03: Hostname label mistakenly containing https:// or http:// scheme."""
        mock_docker_api.return_value = [
            {
                "Names": ["/scheme-in-host"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "https://clean.example.com", "cf.tunnel.port": "80"},
            }
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}, clear=True):
            services, _ = app.get_docker_containers()

        if services:
            self.assertFalse(
                services[0]["hostname"].startswith("http://") or services[0]["hostname"].startswith("https://"),
                f"Hostname should be stripped of protocol scheme, got: {services[0]['hostname']}",
            )

    @patch("app.docker_api")
    def test_empty_or_whitespace_hostname_skipped(self, mock_docker_api):
        """TC-INV-04: Empty string or whitespace-only hostname must be skipped."""
        mock_docker_api.return_value = [
            {
                "Names": ["/empty-host"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "   ", "cf.tunnel.port": "80"},
            }
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}, clear=True):
            services, _ = app.get_docker_containers()

        self.assertEqual(len(services), 0, "Whitespace/empty hostname should not be discovered as a service")

    @patch("app.docker_api")
    def test_duplicate_hostname_collision(self, mock_docker_api):
        """TC-INV-05: Duplicate hostnames across multiple containers should not generate duplicates."""
        mock_docker_api.return_value = [
            {
                "Names": ["/app-v1"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "dup.example.com", "cf.tunnel.port": "8080"},
            },
            {
                "Names": ["/app-v2"],
                "State": "running",
                "Labels": {"cf.tunnel.hostname": "dup.example.com", "cf.tunnel.port": "8081"},
            },
        ]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}, clear=True):
            services, _ = app.get_docker_containers()

        hosts = [s["hostname"] for s in services]
        self.assertEqual(
            len(hosts),
            len(set(hosts)),
            "Duplicate hostnames must be deduplicated to prevent Cloudflare API 400 rejection",
        )

    @patch("app.docker_api")
    def test_none_labels_handled_gracefully(self, mock_docker_api):
        """TC-INV-06: Container with Labels=None should not throw AttributeError."""
        mock_docker_api.return_value = [{"Names": ["/no-labels-container"], "State": "running", "Labels": None}]
        with patch.dict(os.environ, {"DOMAIN_NAME": "example.com"}, clear=True):
            services, all_c = app.get_docker_containers()

        self.assertEqual(len(services), 0)
        self.assertEqual(len(all_c), 1)


if __name__ == "__main__":
    unittest.main()
