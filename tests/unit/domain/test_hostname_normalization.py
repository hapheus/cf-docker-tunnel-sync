import unittest
from unittest.mock import patch

import app
from app import build_ingress_rules, get_docker_containers, normalize_hostname


class TestHostnameNormalization(unittest.TestCase):
    """Hermetic unit tests for canonical hostname normalization (Finding F03 / Issue #43)."""

    def test_tc_43_01_standard_baseline(self):
        """TC-43-01: Standard lowercase FQDN is preserved unchanged."""
        self.assertEqual(normalize_hostname("app.example.com"), "app.example.com")
        self.assertEqual(normalize_hostname("grafana.internal.net"), "grafana.internal.net")

    def test_tc_43_02_mixed_uppercase(self):
        """TC-43-02: Mixed and uppercase characters are lowercased."""
        self.assertEqual(normalize_hostname("App.Example.COM"), "app.example.com")
        self.assertEqual(normalize_hostname("NEXTCLOUD.HOME.LAB"), "nextcloud.home.lab")

    def test_tc_43_03_trailing_dot(self):
        """TC-43-03: Trailing FQDN dots are stripped."""
        self.assertEqual(normalize_hostname("app.example.com."), "app.example.com")
        self.assertEqual(normalize_hostname("service.domain.co.uk."), "service.domain.co.uk")

    def test_tc_43_04_whitespace_trimming(self):
        """TC-43-04: Leading, trailing, and embedded boundary whitespace is trimmed."""
        self.assertEqual(normalize_hostname("  app.example.com  "), "app.example.com")
        self.assertEqual(normalize_hostname("\tapi.example.com\n"), "api.example.com")

    def test_tc_43_05_scheme_stripping(self):
        """TC-43-05: Leading URL schemes (http://, https://) are stripped."""
        self.assertEqual(normalize_hostname("https://app.example.com"), "app.example.com")
        self.assertEqual(normalize_hostname("http://portal.example.com"), "portal.example.com")

    def test_tc_43_06_path_stripping(self):
        """TC-43-06: Trailing URL paths, queries, and fragments are stripped."""
        self.assertEqual(normalize_hostname("app.example.com/api"), "app.example.com")
        self.assertEqual(normalize_hostname("app.example.com/path/to/resource?query=1#hash"), "app.example.com")

    def test_tc_43_07_compound_dirty_input(self):
        """TC-43-07: Compound dirty input (scheme + mixed case + trailing dot + path) is normalized."""
        self.assertEqual(normalize_hostname("HTTPS://App.Example.COM./"), "app.example.com")
        self.assertEqual(
            normalize_hostname("  http://Vault.HomeLab.Org.:8080/v1/auth?client_id=1#token  "),
            "vault.homelab.org",
        )

    def test_tc_43_08_reconciliation_idempotency_dns_casing(self):
        """TC-43-08: Mixed-case container labels reconcile identically with existing Cloudflare DNS records."""
        # Setup mock sync state
        app.sync_state["status"] = "Initializing"
        app.sync_state["docker_connected"] = True
        app.sync_state["tombstones"] = {}
        app.sync_state["synced_dns_records"] = []

        # Container has mixed case label
        mock_containers = [
            {
                "Id": "c1234567890ab",
                "Names": ["/web-app"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "App.Example.COM",
                    "cf.tunnel.port": "8080",
                },
                "NetworkSettings": {"Networks": {"cf-tunnel-net": {}}},
            }
        ]

        # Cloudflare already has canonical lowercase CNAME
        mock_cf_dns_records = {
            "result": [
                {
                    "id": "rec-123",
                    "name": "app.example.com",
                    "type": "CNAME",
                    "content": "test-uuid.cfargotunnel.com",
                }
            ]
        }

        with (
            patch.dict(
                "os.environ",
                {
                    "CLOUDFLARE_API_TOKEN": "mock-token",
                    "DOMAIN_NAME": "example.com",
                    "CLOUDFLARE_TUNNEL_NAME": "test-tunnel",
                    "CF_NETWORK_NAME": "cf-tunnel-net",
                },
            ),
            patch("app.docker_api", return_value=mock_containers),
            patch("app.cf_api") as mock_cf_api,
        ):

            def side_effect(endpoint, token, method="GET", data=None):
                if "/zones?name=" in endpoint:
                    return {"result": [{"id": "zone-123", "name": "example.com"}]}
                if "/cfd_tunnel" in endpoint and "/configurations" in endpoint:
                    return {"result": {"config": {}}}
                if "/cfd_tunnel" in endpoint:
                    return {"result": [{"id": "tunnel-123", "name": "test-tunnel"}]}
                if "/dns_records?type=CNAME&name=app.example.com" in endpoint:
                    return mock_cf_dns_records
                if "/dns_records?type=CNAME&content=" in endpoint:
                    return mock_cf_dns_records
                return {"result": []}

            mock_cf_api.side_effect = side_effect

            app.run_sync_logic()

            # Verify no POST (new record creation) was executed because record already exists
            post_calls = [
                call
                for call in mock_cf_api.call_args_list
                if call.kwargs.get("method") == "POST" and "/dns_records" in call.args[0]
            ]
            self.assertEqual(
                len(post_calls), 0, f"Expected 0 POST calls for existing DNS record, got {len(post_calls)}"
            )

            # Verify no DELETE was called (no false tombstone deletion)
            delete_calls = [call for call in mock_cf_api.call_args_list if call.kwargs.get("method") == "DELETE"]
            self.assertEqual(len(delete_calls), 0, f"Expected 0 DELETE calls, got {len(delete_calls)}")

            # Tombstones should remain empty
            self.assertEqual(len(app.sync_state["tombstones"]), 0)

    def test_tc_43_09_rfc1123_invalid_hostnames_rejected(self):
        """TC-43-09: Invalid RFC 1123 hostnames return None and are safely rejected."""
        invalid_inputs = [
            "-invalid-.com",  # Label starts/ends with hyphen
            "app..example.com",  # Empty label / consecutive dots
            "",  # Empty string
            "   ",  # Whitespace only
            None,  # NoneType
            "invalid_char.com",  # Underscore in hostname
            "a" * 64 + ".com",  # Label exceeds 63 characters
            "example." + "b" * 64,  # TLD exceeds 63 characters
            "foo.-bar.com",  # Label starts with hyphen
            "foo.bar-.com",  # Label ends with hyphen
            "http://",  # Only scheme
            "://",  # Empty scheme
        ]

        for invalid in invalid_inputs:
            with self.subTest(invalid=invalid):
                self.assertIsNone(
                    normalize_hostname(invalid), f"Expected normalize_hostname({invalid!r}) to return None"
                )

    def test_docker_containers_rejects_invalid_hostname(self):
        """Invalid container hostname labels are skipped from discovered services and logged."""
        mock_containers = [
            {
                "Id": "c_bad_1",
                "Names": ["/bad-container"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "-bad-hostname-.com",
                    "cf.tunnel.port": "8080",
                },
                "NetworkSettings": {"Networks": {"cf-tunnel-net": {}}},
            },
            {
                "Id": "c_good_1",
                "Names": ["/good-container"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "Good.Example.COM.",
                    "cf.tunnel.port": "8080",
                },
                "NetworkSettings": {"Networks": {"cf-tunnel-net": {}}},
            },
        ]

        with (
            patch.dict(
                "os.environ",
                {
                    "DOMAIN_NAME": "example.com",
                    "CLOUDFLARE_TUNNEL_NAME": "test-tunnel",
                    "CF_NETWORK_NAME": "cf-tunnel-net",
                },
            ),
            patch("app.docker_api", return_value=mock_containers),
        ):
            services, all_containers = get_docker_containers()

            # Only good-container is included in active sync services
            self.assertEqual(len(services), 1)
            self.assertEqual(services[0]["container"], "good-container")
            self.assertEqual(services[0]["hostname"], "good.example.com")

            # bad-container is not tunneled
            bad_entry = next(c for c in all_containers if c["name"] == "bad-container")
            self.assertFalse(bad_entry["is_tunneled"])

    def test_duplicate_hostname_detection_case_insensitive(self):
        """Duplicate hostnames with varying casing or dots are recognized and ignored."""
        mock_containers = [
            {
                "Id": "c1",
                "Names": ["/first"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "App.Example.COM",
                    "cf.tunnel.port": "8080",
                },
                "NetworkSettings": {"Networks": {"cf-tunnel-net": {}}},
            },
            {
                "Id": "c2",
                "Names": ["/second"],
                "State": "running",
                "Labels": {
                    "cf.tunnel.enable": "true",
                    "cf.tunnel.hostname": "app.example.com.",
                    "cf.tunnel.port": "8081",
                },
                "NetworkSettings": {"Networks": {"cf-tunnel-net": {}}},
            },
        ]

        with (
            patch.dict(
                "os.environ",
                {
                    "DOMAIN_NAME": "example.com",
                    "CLOUDFLARE_TUNNEL_NAME": "test-tunnel",
                    "CF_NETWORK_NAME": "cf-tunnel-net",
                },
            ),
            patch("app.docker_api", return_value=mock_containers),
        ):
            services, _ = get_docker_containers()
            self.assertEqual(len(services), 1)
            self.assertEqual(services[0]["container"], "first")
            self.assertEqual(services[0]["hostname"], "app.example.com")

    def test_build_ingress_rules_normalizes_hostnames(self):
        """build_ingress_rules normalizes hostnames and sorts deterministically."""
        services = [
            {"hostname": "Zebra.Example.COM.", "service": "http://zebra:80"},
            {"hostname": "ALPHA.EXAMPLE.COM", "service": "http://alpha:80"},
            {"hostname": "   ", "service": "http://invalid:80"},
            {"hostname": "-bad-.com", "service": "http://invalid:80"},
        ]

        rules = build_ingress_rules(services)

        # Catch-all is always the last rule
        self.assertEqual(len(rules), 3)  # 2 valid normalized + 1 catch-all 404
        self.assertEqual(rules[0]["hostname"], "alpha.example.com")
        self.assertEqual(rules[1]["hostname"], "zebra.example.com")
        self.assertEqual(rules[2]["service"], "http_status:404")


if __name__ == "__main__":
    unittest.main()
