"""Tests for Milestone 2 Package B:

- #103: SAFE-03: Network reachability & remediation
- #104: SAFE-04: Dashboard exposure & auth fail-closed
- #108: SEC-01: Docker socket proxy & TCP connection
- #111: OPS-04: Truthful diagnostic health reporting
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import app
from diagnostics import (
    DiagnosticStageName,
    DiagnosticStageStatus,
    compute_truthful_service_status,
    evaluate_service_stages,
)
from starlette.testclient import TestClient


class TestM2PackageB(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["logs"] = []
        app.sync_state["docker_connected"] = True

    def test_sec_01_docker_host_tcp_socket_proxy(self):
        """SEC-01: When DOCKER_HOST is set to tcp://proxy:2375, docker_api connects via standard HTTPConnection."""
        with (
            patch.dict(os.environ, {"DOCKER_HOST": "tcp://docker-socket-proxy:2375"}),
            patch("http.client.HTTPConnection") as mock_http_conn,
        ):
            mock_conn_instance = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b'[{"Id": "c1", "Names": ["/test"]}]'
            mock_conn_instance.getresponse.return_value = mock_resp
            mock_http_conn.return_value = mock_conn_instance

            res = app.docker_api("/containers/json")

            self.assertEqual(len(res), 1)
            mock_http_conn.assert_called_once_with("docker-socket-proxy", 2375, timeout=10.0)

    def test_safe_03_isolated_network_outputs_compose_remediation(self):
        """SAFE-03: When an origin container is missing shared network with cloudflared,

        the diagnostic stage outputs the exact Compose snippet to attach cf-tunnel-net.
        """
        stages = evaluate_service_stages(
            hostname="unreachable.example.com",
            raw_hostname="unreachable.example.com",
            is_hostname_valid=True,
            domain_matches=True,
            configured_domain="example.com",
            network_connected=False,
            container_state="running",
            ingress_status="PASS",
            dns_status="PASS",
        )

        stage_3 = stages[DiagnosticStageName.NETWORK_TOPOLOGY.value]
        self.assertEqual(stage_3["status"], DiagnosticStageStatus.WARNING.value)
        self.assertIn("cf-tunnel-net", stage_3["message"])
        self.assertIn("Remediation", stage_3["message"])

        # Service must be reported as Degraded, never Synced
        status = compute_truthful_service_status(stages)
        self.assertEqual(status, "Degraded")

    def test_safe_04_dashboard_auth_fail_closed_on_invalid_credentials(self):
        """SAFE-04: Dashboard authentication fails closed on missing or wrong password."""
        client = TestClient(app.app)

        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "true",
                "DASHBOARD_USERNAME": "admin",
                "DASHBOARD_PASSWORD": "securepassword123",
            },
        ):
            # 1. No auth headers -> 401
            resp_no_auth = client.get("/api/status")
            self.assertEqual(resp_no_auth.status_code, 401)

            # 2. Wrong credentials -> 401
            resp_wrong = client.get("/api/status", auth=("admin", "wrongpass"))
            self.assertEqual(resp_wrong.status_code, 401)

            # 3. Correct credentials -> 200
            resp_ok = client.get("/api/status", auth=("admin", "securepassword123"))
            self.assertEqual(resp_ok.status_code, 200)

    def test_ops_04_truthful_diagnostics_distinguish_failure_and_pending_states(self):
        """OPS-04: Truthful diagnostics correctly distinguish Configured/Pending, Degraded, and Failed states."""
        # 1. Label syntax invalid -> Failed
        stages_fail = evaluate_service_stages(
            hostname=None,
            raw_hostname="invalid..syntax",
            is_hostname_valid=False,
            domain_matches=False,
            configured_domain="example.com",
            network_connected=True,
            container_state="running",
        )
        self.assertEqual(compute_truthful_service_status(stages_fail), "Failed")

        # 2. Ingress pending -> Pending
        stages_pending = evaluate_service_stages(
            hostname="web.example.com",
            raw_hostname="web.example.com",
            is_hostname_valid=True,
            domain_matches=True,
            configured_domain="example.com",
            network_connected=True,
            container_state="running",
            ingress_status="PENDING",
        )
        self.assertEqual(compute_truthful_service_status(stages_pending), "Pending")


if __name__ == "__main__":
    unittest.main()
