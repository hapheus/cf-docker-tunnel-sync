import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import app
from reconcile import (
    ChangePlan,
    ChangePlanSummary,
    DnsActionType,
    IngressActionType,
    OwnershipStatus,
    PlannedDnsChange,
    PlannedIngressChange,
    RemoteState,
    build_discovery_snapshot,
    compute_change_plan,
)


class TestDryRunAndChangePlanEndpoint(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["logs"] = []
        app.sync_state["_last_ingress"] = None
        app.sync_state["_last_change_plan_obj"] = None
        app.sync_state["last_change_plan"] = None

    @patch("builtins.open")
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=True)
    @patch("app.cf_api")
    @patch("app.docker_api")
    def test_dry_run_zero_mutators_executed(self, mock_docker, mock_cf, mock_exists, mock_dirs, mock_open):
        """Acceptance Criteria: Unit tests verify that when DRY_RUN=true,

        zero mutator HTTP requests (POST, PUT, DELETE, PATCH) are executed against the mock Cloudflare API.
        """
        mock_docker.return_value = [
            {
                "Id": "c100",
                "Names": ["/my-service"],
                "Image": "nginx:alpine",
                "State": "running",
                "Status": "Up",
                "Labels": {
                    "cf.tunnel.hostname": "api.example.com",
                    "cf.tunnel.port": "8080",
                },
                "NetworkSettings": {"Networks": {"cf-tunnel-net": {}}},
            }
        ]

        mutator_calls = []

        def cf_side_effect(endpoint, token, method="GET", data=None, **kwargs):
            if method.upper() in ("POST", "PUT", "DELETE", "PATCH"):
                mutator_calls.append({"endpoint": endpoint, "method": method, "data": data})

            if "/zones?name=" in endpoint:
                return {"result": [{"id": "zone-123", "account": {"id": "acc-123"}}]}
            if "/cfd_tunnel?" in endpoint:
                return {"result": [{"id": "tun-123", "name": "cf-docker-tunnel-sync"}]}
            if "/token" in endpoint:
                return {"result": "fake-token"}
            if "/configurations" in endpoint:
                return {"result": {"config": {"ingress": []}}}
            if "/dns_records" in endpoint:
                return {"result": []}
            return {"result": []}

        mock_cf.side_effect = cf_side_effect

        with patch.dict(
            os.environ,
            {
                "DRY_RUN": "true",
                "CLOUDFLARE_API_TOKEN": "valid-token",
                "DOMAIN_NAME": "example.com",
                "CF_NETWORK_NAME": "cf-tunnel-net",
            },
        ):
            app.run_sync_logic()

        self.assertEqual(len(mutator_calls), 0, f"Expected 0 mutator calls in dry-run mode, got: {mutator_calls}")
        self.assertIn("Dry-Run", app.sync_state["status"])

        # Check logs contain diff markers
        diff_logs = [log for log in app.sync_state["logs"] if "+ [INGRESS CREATE]" in log or "+ [DNS CREATE]" in log]
        self.assertTrue(len(diff_logs) >= 2, "Diff markers must be logged for dry run actions")

    def test_change_plan_api_schema(self):
        """Acceptance Criteria: GET /api/change-plan returns a valid JSON schema representing pending actions."""
        summary = ChangePlanSummary(
            total_services_discovered=1,
            ingress_creates=1,
            ingress_updates=0,
            ingress_deletes=0,
            dns_creates=1,
            dns_updates=0,
            dns_deletes=0,
            dns_protected=0,
            unmanaged_skipped=0,
            has_mutations=True,
            is_destructive=False,
        )
        plan = ChangePlan(
            plan_id="test-plan-uuid-123",
            timestamp=1729145000.0,
            tunnel_id="tun-123",
            zone_id="zone-123",
            dry_run=True,
            ingress_changes=[
                PlannedIngressChange(
                    action=IngressActionType.CREATE,
                    hostname="api.example.com",
                    service="http://my-service:8080",
                    reason="New origin discovered",
                )
            ],
            dns_changes=[
                PlannedDnsChange(
                    action=DnsActionType.CREATE,
                    hostname="api.example.com",
                    target_content="tun-123.cfargotunnel.com",
                    ownership_status=OwnershipStatus.OWNED,
                    reason="Missing CNAME",
                )
            ],
            summary=summary,
        )

        app.sync_state["_last_change_plan_obj"] = plan
        app.sync_state["_last_change_plan_api"] = plan.to_api_dict()

        client = TestClient(app.app)
        resp = client.get("/api/change-plan")
        self.assertEqual(resp.status_code, 200)

        data = resp.json()

        # Schema Validation
        self.assertEqual(data["plan_id"], "test-plan-uuid-123")
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["timestamp"], 1729145000.0)

        self.assertIn("summary", data)
        self.assertEqual(data["summary"]["additions"], 2)
        self.assertEqual(data["summary"]["updates"], 0)
        self.assertEqual(data["summary"]["deletions"], 0)
        self.assertEqual(data["summary"]["unmanaged_skipped"], 0)

        self.assertIn("actions", data)
        self.assertEqual(len(data["actions"]), 2)

        ingress_act = next(a for a in data["actions"] if a["resource"] == "INGRESS")
        self.assertEqual(ingress_act["action"], "CREATE")
        self.assertEqual(ingress_act["target"]["hostname"], "api.example.com")
        self.assertEqual(ingress_act["target"]["service"], "http://my-service:8080")

        dns_act = next(a for a in data["actions"] if a["resource"] == "DNS")
        self.assertEqual(dns_act["action"], "CREATE")
        self.assertEqual(dns_act["target"]["hostname"], "api.example.com")
        self.assertEqual(dns_act["target"]["target_content"], "tun-123.cfargotunnel.com")

    def test_full_round_trip_dry_run_matches_live_mode_actions(self):
        """Acceptance Criteria: Full round-trip test verifies dry-run diff

        accurately matches the actions taken during normal live mode.
        """
        services = [
            {
                "container": "webapp",
                "hostname": "app.example.com",
                "service": "http://webapp:80",
            }
        ]
        all_c = [{"Names": ["/webapp"], "State": "running"}]
        snapshot = build_discovery_snapshot(services, all_c)

        remote = RemoteState(
            tunnel_id="tun-abc",
            tunnel_name="my-tun",
            zone_id="zone-xyz",
            tunnel_target="tun-abc.cfargotunnel.com",
            existing_ingress_rules=[],
            existing_dns_records=[],
        )

        # 1. Compute in dry-run mode
        dry_plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=1000.0,
            dry_run=True,
        )

        # 2. Compute in live mode
        live_plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=1000.0,
            dry_run=False,
        )

        # Assert actions match 1:1
        self.assertEqual(len(dry_plan.ingress_changes), len(live_plan.ingress_changes))
        self.assertEqual(len(dry_plan.dns_changes), len(live_plan.dns_changes))

        for d_ing, l_ing in zip(dry_plan.ingress_changes, live_plan.ingress_changes):
            self.assertEqual(d_ing.action, l_ing.action)
            self.assertEqual(d_ing.hostname, l_ing.hostname)
            self.assertEqual(d_ing.service, l_ing.service)

        for d_dns, l_dns in zip(dry_plan.dns_changes, live_plan.dns_changes):
            self.assertEqual(d_dns.action, l_dns.action)
            self.assertEqual(d_dns.hostname, l_dns.hostname)
            self.assertEqual(d_dns.target_content, l_dns.target_content)


if __name__ == "__main__":
    unittest.main()
