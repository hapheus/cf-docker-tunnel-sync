import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import app
from diagnostics import (
    DiagnosticStageName,
    DiagnosticStageStatus,
    compute_truthful_service_status,
    evaluate_service_stages,
)


class TestDiagnosticsPipelineAndTruthfulReporting(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["logs"] = []
        app.sync_state["services"] = []
        app.sync_state["discovered_services"] = []
        app.sync_state["all_containers"] = []
        app.sync_state["safety_guard_tripped"] = False
        app.sync_state["safety_details"] = None

    def test_six_stages_distinct_deterministic_enums(self):
        """Verifies each of the 6 stages produces distinct, deterministic status enums."""
        stages = evaluate_service_stages(
            hostname="web.example.com",
            raw_hostname="web.example.com",
            is_hostname_valid=True,
            domain_matches=True,
            configured_domain="example.com",
            network_connected=True,
            container_state="running",
            ingress_status=DiagnosticStageStatus.PASS.value,
            dns_status=DiagnosticStageStatus.PASS.value,
        )

        expected_stages = [
            DiagnosticStageName.LABEL_SYNTAX.value,
            DiagnosticStageName.TUNNEL_DOMAIN_MATCH.value,
            DiagnosticStageName.NETWORK_TOPOLOGY.value,
            DiagnosticStageName.CLOUDFLARE_INGRESS.value,
            DiagnosticStageName.CLOUDFLARE_DNS.value,
            DiagnosticStageName.ORIGIN_HEALTH.value,
        ]

        for stage_name in expected_stages:
            self.assertIn(stage_name, stages)
            self.assertIn("status", stages[stage_name])
            self.assertIn("message", stages[stage_name])
            # Ensure status is a valid enum value
            self.assertIn(stages[stage_name]["status"], [e.value for e in DiagnosticStageStatus])

        # All pass -> Synced
        status = compute_truthful_service_status(stages)
        self.assertEqual(status, "Synced")

    def test_stage_1_label_syntax_failure(self):
        """Invalid hostname or label syntax marks Stage 1 as FAILED and status as Failed."""
        stages = evaluate_service_stages(
            hostname=None,
            raw_hostname="invalid..hostname",
            is_hostname_valid=False,
            domain_matches=False,
            configured_domain="example.com",
            network_connected=True,
            container_state="running",
        )
        self.assertEqual(stages[DiagnosticStageName.LABEL_SYNTAX.value]["status"], DiagnosticStageStatus.FAILED.value)
        status = compute_truthful_service_status(stages)
        self.assertEqual(status, "Failed")

    def test_stage_2_domain_mismatch_failure(self):
        """Domain mismatch marks Stage 2 as FAILED and status as Failed."""
        stages = evaluate_service_stages(
            hostname="app.otherdomain.com",
            raw_hostname="app.otherdomain.com",
            is_hostname_valid=True,
            domain_matches=False,
            configured_domain="example.com",
            network_connected=True,
            container_state="running",
        )
        self.assertEqual(
            stages[DiagnosticStageName.TUNNEL_DOMAIN_MATCH.value]["status"], DiagnosticStageStatus.FAILED.value
        )
        status = compute_truthful_service_status(stages)
        self.assertEqual(status, "Failed")

    def test_stage_3_network_topology_warning(self):
        """Network isolation marks Stage 3 as WARNING."""
        stages = evaluate_service_stages(
            hostname="web.example.com",
            raw_hostname="web.example.com",
            is_hostname_valid=True,
            domain_matches=True,
            configured_domain="example.com",
            network_connected=False,
            network_warning="Missing shared network",
            container_state="running",
        )
        self.assertEqual(
            stages[DiagnosticStageName.NETWORK_TOPOLOGY.value]["status"], DiagnosticStageStatus.WARNING.value
        )

    def test_stage_4_ingress_failure_truthful_reporting(self):
        """Acceptance Criteria: Ingress failure correctly marks stage 4 as FAILED

        and overall state as DEGRADED (never SYNCED).
        """
        stages = evaluate_service_stages(
            hostname="web.example.com",
            raw_hostname="web.example.com",
            is_hostname_valid=True,
            domain_matches=True,
            configured_domain="example.com",
            network_connected=True,
            container_state="running",
            ingress_status=DiagnosticStageStatus.FAILED.value,
            ingress_message="Cloudflare Ingress PUT returned 500 Internal Error",
            dns_status=DiagnosticStageStatus.PASS.value,
        )

        self.assertEqual(
            stages[DiagnosticStageName.CLOUDFLARE_INGRESS.value]["status"], DiagnosticStageStatus.FAILED.value
        )
        service_status = compute_truthful_service_status(stages)
        self.assertEqual(service_status, "Degraded", "Service must be Degraded, not Synced")

    @patch("builtins.open")
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=True)
    @patch("app.cf_api")
    @patch("app.docker_api")
    def test_sync_cycle_with_ingress_failure_sets_overall_degraded(
        self, mock_docker, mock_cf, mock_exists, mock_dirs, mock_open
    ):
        """End-to-end sync cycle where Cloudflare Ingress fails sets overall sync status to Degraded."""
        mock_docker.return_value = [
            {
                "Id": "c123",
                "Names": ["/my-web-app"],
                "Image": "nginx:alpine",
                "State": "running",
                "Status": "Up 2 hours",
                "Labels": {
                    "cf.tunnel.hostname": "web.example.com",
                    "cf.tunnel.port": "80",
                },
                "NetworkSettings": {"Networks": {"cf-tunnel-net": {}}},
            }
        ]

        def cf_mock(endpoint, token, method="GET", data=None, **kwargs):
            if "/zones?name=" in endpoint:
                return {"result": [{"id": "zone-123", "account": {"id": "acc-123"}}]}
            if "/cfd_tunnel?" in endpoint:
                return {"result": [{"id": "tun-123", "name": "cf-docker-tunnel-sync"}]}
            if "/token" in endpoint:
                return {"result": "fake-token"}
            if "/configurations" in endpoint:
                if method.upper() == "PUT":
                    raise RuntimeError("Cloudflare API PUT 500 error")
                return {"result": {"config": {"ingress": []}}}
            if "/dns_records" in endpoint:
                return {"result": []}
            return {"result": []}

        mock_cf.side_effect = cf_mock

        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_API_TOKEN": "token-xyz",
                "DOMAIN_NAME": "example.com",
                "CF_NETWORK_NAME": "cf-tunnel-net",
            },
        ):
            app.run_sync_logic()

        # Ingress failed -> overall status must be Degraded (NOT Synced)
        self.assertEqual(app.sync_state["status"], "Degraded")
        self.assertTrue(len(app.sync_state["services"]) > 0)
        svc = app.sync_state["services"][0]
        self.assertEqual(svc["stages"][DiagnosticStageName.CLOUDFLARE_INGRESS.value]["status"], "FAILED")
        self.assertEqual(svc["status"], "Degraded")

    def test_status_api_json_schema_compatibility(self):
        """Hermetic API test validates JSON schema compatibility of /api/status with legacy and modern consumers."""
        sample_stages = evaluate_service_stages(
            hostname="web.example.com",
            raw_hostname="web.example.com",
            is_hostname_valid=True,
            domain_matches=True,
            configured_domain="example.com",
            network_connected=True,
            container_state="running",
            ingress_status=DiagnosticStageStatus.PASS.value,
            dns_status=DiagnosticStageStatus.PASS.value,
        )

        app.sync_state["status"] = "Active / Synced"
        app.sync_state["domain_name"] = "example.com"
        app.sync_state["tunnel_name"] = "test-tunnel"
        app.sync_state["services"] = [
            {
                "hostname": "web.example.com",
                "status": "Synced",
                "service": "http://my-app:80",
                "network_connected": True,
                "stages": sample_stages,
            }
        ]
        app.sync_state["discovered_services"] = app.sync_state["services"]

        client = TestClient(app.app)
        resp = client.get("/api/status")
        self.assertEqual(resp.status_code, 200)

        data = resp.json()

        # Backward compatibility assertions for legacy consumers:
        self.assertIn("status", data)
        self.assertIn("domain_name", data)
        self.assertIn("tunnel_name", data)
        self.assertIn("discovered_services", data)
        self.assertIn("services", data)

        legacy_service = data["services"][0]
        self.assertEqual(legacy_service["hostname"], "web.example.com")
        self.assertEqual(legacy_service["status"], "Synced")

        # Modern additive diagnostic stages assertion:
        self.assertIn("stages", legacy_service)
        self.assertEqual(legacy_service["stages"]["CLOUDFLARE_INGRESS"]["status"], "PASS")
        self.assertEqual(legacy_service["stages"]["CLOUDFLARE_DNS"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
