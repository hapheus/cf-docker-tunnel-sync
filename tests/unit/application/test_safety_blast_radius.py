import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import app


class TestSafetyBlastRadiusGuard(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["logs"] = []
        app.sync_state["safety_guard_tripped"] = False
        app.sync_state["safety_details"] = None
        app.sync_state["_last_ingress"] = None

    @patch("builtins.open")
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=True)
    @patch("app.cf_api")
    @patch("app.docker_api")
    def test_blast_radius_aborts_when_four_containers_removed_and_limit_three(
        self, mock_docker, mock_cf, mock_exists, mock_dirs, mock_open
    ):
        """Acceptance Criteria: Unit test verifies that if 4 containers are removed

        when MAX_DELETIONS_PER_SYNC=3, sync aborts and zero deletions are sent to Cloudflare.
        """
        # Docker discovery returns 0 containers (4 containers were stopped/removed)
        mock_docker.return_value = []

        deletion_calls = []

        # Cloudflare currently has 4 managed ingress rules and 4 DNS records
        existing_rules = [{"hostname": f"service{i}.example.com", "service": f"http://svc{i}:80"} for i in range(1, 5)]
        existing_rules.append({"service": "http_status:404"})

        existing_dns = {
            f"rec-{i}": {
                "id": f"rec-{i}",
                "name": f"service{i}.example.com",
                "content": "tun-123.cfargotunnel.com",
                "type": "CNAME",
                "comment": "cf-tunnel-sync:cf-docker-tunnel-sync",
            }
            for i in range(1, 5)
        }

        def cf_mock(endpoint, token, method="GET", data=None, **kwargs):
            if method.upper() in ("DELETE", "PUT", "POST"):
                if method.upper() == "DELETE" or (method.upper() == "PUT" and "/configurations" in endpoint):
                    deletion_calls.append({"endpoint": endpoint, "method": method, "data": data})

            if "/zones?name=" in endpoint:
                return {"result": [{"id": "zone-123", "account": {"id": "acc-123"}}]}
            if "/cfd_tunnel?" in endpoint:
                return {"result": [{"id": "tun-123", "name": "cf-docker-tunnel-sync"}]}
            if "/token" in endpoint:
                return {"result": "fake-token"}
            if "/configurations" in endpoint:
                return {"result": {"config": {"ingress": existing_rules}}}
            if "/dns_records" in endpoint:
                return {"result": list(existing_dns.values())}
            return {"result": []}

        mock_cf.side_effect = cf_mock

        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_API_TOKEN": "token-xyz",
                "DOMAIN_NAME": "example.com",
                "MAX_DELETIONS_PER_SYNC": "3",
                "ALLOW_MASS_DELETIONS": "false",
                "DNS_CLEANUP_GRACE_PERIOD": "0",
                "DNS_IMMEDIATE_CLEANUP": "true",
            },
        ):
            app.run_sync_logic()

        # Zero deletions must have been sent to Cloudflare
        delete_methods = [c for c in deletion_calls if c["method"] == "DELETE"]
        self.assertEqual(len(delete_methods), 0, "No DELETE calls should be made when safety guard trips")

        # Safety trip status accurately reported in sync_state
        self.assertEqual(app.sync_state["status"], "SAFETY_GUARD_TRIPPED")
        self.assertTrue(app.sync_state["safety_guard_tripped"])

        # Safety guard warning logged
        safety_logs = [log for log in app.sync_state["logs"] if "[SAFETY_GUARD]" in log]
        self.assertTrue(len(safety_logs) > 0, "Expected [SAFETY_GUARD] abort warning in logs")

        # Acceptance Criteria: Safety trip status is accurately reported in /api/status
        client = TestClient(app.app)
        resp = client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "SAFETY_GUARD_TRIPPED")
        self.assertTrue(data.get("safety_guard_tripped"))

    @patch("builtins.open")
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=True)
    @patch("app.cf_api")
    @patch("app.docker_api")
    def test_mass_deletion_override_permits_deletions(self, mock_docker, mock_cf, mock_exists, mock_dirs, mock_open):
        """Acceptance Criteria: When ALLOW_MASS_DELETIONS=true is set,

        deletions exceeding the threshold are permitted and executed cleanly.
        """
        mock_docker.return_value = []

        existing_rules = [{"hostname": f"service{i}.example.com", "service": f"http://svc{i}:80"} for i in range(1, 5)]
        existing_rules.append({"service": "http_status:404"})

        existing_dns = {
            f"rec-{i}": {
                "id": f"rec-{i}",
                "name": f"service{i}.example.com",
                "content": "tun-123.cfargotunnel.com",
                "type": "CNAME",
                "comment": "cf-tunnel-sync:cf-docker-tunnel-sync",
            }
            for i in range(1, 5)
        }

        deletion_calls = []

        def cf_mock(endpoint, token, method="GET", data=None, **kwargs):
            if method.upper() == "DELETE":
                deletion_calls.append({"endpoint": endpoint, "method": method})

            if "/zones?name=" in endpoint:
                return {"result": [{"id": "zone-123", "account": {"id": "acc-123"}}]}
            if "/cfd_tunnel?" in endpoint:
                return {"result": [{"id": "tun-123", "name": "cf-docker-tunnel-sync"}]}
            if "/token" in endpoint:
                return {"result": "fake-token"}
            if "/configurations" in endpoint:
                return {"result": {"config": {"ingress": existing_rules}}}
            if "/dns_records" in endpoint:
                return {"result": list(existing_dns.values())}
            return {"result": []}

        mock_cf.side_effect = cf_mock

        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_API_TOKEN": "token-xyz",
                "DOMAIN_NAME": "example.com",
                "MAX_DELETIONS_PER_SYNC": "3",
                "ALLOW_MASS_DELETIONS": "true",  # Explicit override
                "DNS_CLEANUP_GRACE_PERIOD": "0",
                "DNS_IMMEDIATE_CLEANUP": "true",
            },
        ):
            app.run_sync_logic()

        # Deletions were permitted and executed
        self.assertEqual(len(deletion_calls), 4, "All 4 DNS deletions must be executed under mass deletion override")
        self.assertNotEqual(app.sync_state["status"], "SAFETY_GUARD_TRIPPED")
        self.assertEqual(app.sync_state["status"], "Active / Synced")

        override_logs = [log for log in app.sync_state["logs"] if "Mass deletion override active" in log]
        self.assertTrue(len(override_logs) > 0, "Expected override notice in logs")

    @patch("builtins.open")
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=True)
    @patch("app.cf_api")
    @patch("app.docker_api")
    def test_max_deletion_ratio_aborts_when_ratio_exceeded(
        self, mock_docker, mock_cf, mock_exists, mock_dirs, mock_open
    ):
        """Verifies MAX_DELETION_RATIO threshold aborts sync when ratio of deleted routes exceeds limit."""
        # 2 active containers remaining out of 4
        mock_docker.return_value = [
            {
                "Id": f"c{i}",
                "Names": [f"/service{i}"],
                "Image": "nginx:alpine",
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cf.tunnel.hostname": f"service{i}.example.com",
                    "cf.tunnel.port": "80",
                },
                "NetworkSettings": {"Networks": {"cf-tunnel-net": {}}},
            }
            for i in range(1, 3)
        ]

        existing_rules = [{"hostname": f"service{i}.example.com", "service": f"http://svc{i}:80"} for i in range(1, 5)]
        existing_rules.append({"service": "http_status:404"})

        existing_dns = {
            f"rec-{i}": {
                "id": f"rec-{i}",
                "name": f"service{i}.example.com",
                "content": "tun-123.cfargotunnel.com",
                "type": "CNAME",
                "comment": "cf-tunnel-sync:cf-docker-tunnel-sync",
            }
            for i in range(1, 5)
        }

        def cf_mock(endpoint, token, method="GET", data=None, **kwargs):
            if "/zones?name=" in endpoint:
                return {"result": [{"id": "zone-123", "account": {"id": "acc-123"}}]}
            if "/cfd_tunnel?" in endpoint:
                return {"result": [{"id": "tun-123", "name": "cf-docker-tunnel-sync"}]}
            if "/token" in endpoint:
                return {"result": "fake-token"}
            if "/configurations" in endpoint:
                return {"result": {"config": {"ingress": existing_rules}}}
            if "/dns_records" in endpoint:
                return {"result": list(existing_dns.values())}
            return {"result": []}

        mock_cf.side_effect = cf_mock

        # Limit count is 10, but MAX_DELETION_RATIO is 0.3 (30%).
        # Planned deletions: 2 routes out of 4 total (50% ratio) -> exceeds 30%!
        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_API_TOKEN": "token-xyz",
                "DOMAIN_NAME": "example.com",
                "MAX_DELETIONS_PER_SYNC": "10",
                "MAX_DELETION_RATIO": "0.3",
                "ALLOW_MASS_DELETIONS": "false",
                "DNS_CLEANUP_GRACE_PERIOD": "0",
                "DNS_IMMEDIATE_CLEANUP": "true",
            },
        ):
            app.run_sync_logic()

        self.assertEqual(app.sync_state["status"], "SAFETY_GUARD_TRIPPED")
        self.assertTrue(app.sync_state["safety_guard_tripped"])


if __name__ == "__main__":
    unittest.main()
