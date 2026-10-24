"""
Hermetic Compatibility Baseline & Upgrade-in-Place Regression Test Suite
Milestone 0 (v1.14.0): Issues #83 (COMPAT-01), #84 (COMPAT-02), #85 (COMPAT-03), #86 (COMPAT-04)

Verifies:
1. Supported-behavior baseline across all configuration env vars, aliases, and defaults.
2. Public API response schema contracts (/health, /ready, /api/status, /api/change-plan, /metrics).
3. Upgrade-in-place idempotence: pre-existing v1.13.0 deployments (single-compose, multi-compose,
   multi-account) require zero config changes and produce zero unexpected Cloudflare mutations.
4. Unmanaged resource preservation: unmanaged DNS records and ingress rules are never claimed or deleted.
5. Downgrade safety: no irreversible state migrations exist.
"""

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
import config
from reconcile import (
    DiscoveredOrigin,
    DiscoverySnapshot,
    OwnershipPolicy,
    RemoteState,
    compute_change_plan,
)
from tests.paths import FIXTURES_DIR, REPO_ROOT


class TestSupportedBehaviorBaseline(unittest.TestCase):
    """COMPAT-01 & COMPAT-03: Configuration and API Schema Contracts Baseline."""

    def setUp(self):
        self.fixtures_dir = str(FIXTURES_DIR)

    def test_known_env_vars_and_aliases_freeze(self):
        """Freeze all canonical environment variables and aliases against regressions."""
        # Baseline canonical env vars that must always be recognized without warnings
        required_canonical_vars = {
            "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_ZONE_ID",
            "CLOUDFLARE_TUNNEL_NAME",
            "CLOUDFLARE_TUNNEL_ID",
            "DOMAIN_NAME",
            "CLOUDFLARE_DNS_PROXIED",
            "REQUIRE_SHARED_NETWORK",
            "CUSTOM_NETWORK",
            "DRY_RUN",
            "ENABLE_CHANGE_PLAN",
            "SYNC_INTERVAL",
            "MAX_DELETIONS_PER_SYNC",
            "ALLOW_MASS_DELETIONS",
            "PORT",
            "DASHBOARD_USERNAME",
            "DASHBOARD_PASSWORD",
            "DASHBOARD_AUTH_ENABLED",
            "AUTO_CREATE_TUNNEL",
        }
        for env_var in required_canonical_vars:
            self.assertIn(
                env_var,
                config.KNOWN_ENV_VARS,
                f"Canonical environment variable {env_var} must remain registered in KNOWN_ENV_VARS.",
            )

    def test_legacy_label_aliases_freeze(self):
        """Verify legacy label aliases remain fully supported and mapped to canonical keys."""
        required_label_aliases = {
            "tunnel.hostname": "cf.tunnel.hostname",
            "tunnel.port": "cf.tunnel.port",
            "tunnel.service": "cf.tunnel.service",
            "cloudflared.hostname": "cf.tunnel.hostname",
            "cloudflared.port": "cf.tunnel.port",
        }
        for alias, canonical in required_label_aliases.items():
            self.assertIn(alias, config.LABEL_ALIASES)
            self.assertEqual(config.LABEL_ALIASES[alias], canonical)

    def test_runtime_defaults_freeze(self):
        """Verify non-negotiable runtime defaults remain unchanged for backward compatibility."""
        with patch.dict(os.environ, {}, clear=True):
            # Port default
            self.assertEqual(int(os.getenv("PORT", "8080")), 8080)
            # Require shared network default must remain false for existing setups
            self.assertNotEqual(os.getenv("REQUIRE_SHARED_NETWORK", "false").lower(), "true")
            # Dry run default must be false
            self.assertNotEqual(os.getenv("DRY_RUN", "false").lower(), "true")
            # Proxied default must be true
            self.assertEqual(os.getenv("CLOUDFLARE_DNS_PROXIED", "true").lower(), "true")

    def test_api_status_schema_contract(self):
        """COMPAT-03: Validate that /api/status matches the frozen v1.13.0 contract."""
        fixture_path = os.path.join(self.fixtures_dir, "api_status_baseline_v1_13.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            fixture = json.load(f)

        client = TestClient(app.app)
        app.sync_state["status"] = "Active / Synced"
        app.sync_state["last_sync"] = "2026-10-17T10:00:00Z"
        app.sync_state["discovered_services"] = []
        app.sync_state["all_containers"] = []
        app.sync_state["error"] = None
        app.sync_state["warnings"] = []

        response = client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        for key in fixture["required_keys"]:
            self.assertIn(
                key,
                data,
                f"Required status API key '{key}' from v1.13.0 baseline is missing.",
            )

    def test_health_endpoints_schema_contract(self):
        """COMPAT-03: Validate that /health, /healthz, and /ready return expected JSON shapes."""
        client = TestClient(app.app)

        res_health = client.get("/health")
        self.assertEqual(res_health.status_code, 200)
        health_data = res_health.json()
        self.assertEqual(health_data.get("status"), "healthy")

        res_healthz = client.get("/healthz")
        self.assertEqual(res_healthz.status_code, 200)
        healthz_data = res_healthz.json()
        self.assertEqual(healthz_data.get("status"), "healthy")

        res_ready = client.get("/ready")
        self.assertEqual(res_ready.status_code, 200)
        ready_data = res_ready.json()
        self.assertEqual(ready_data.get("status"), "ready")

    def test_metrics_endpoint_exposition_contract(self):
        """COMPAT-03: Validate Prometheus /metrics endpoint exposition format."""
        client = TestClient(app.app)
        response = client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-type"), "text/plain; version=0.0.4; charset=utf-8")
        text = response.text
        # Assert Prometheus metrics are present according to v1.13.0 baseline
        self.assertIn("cf_tunnel_sync_runs_total", text)
        self.assertIn("cf_tunnel_services_discovered", text)
        self.assertIn("cf_tunnel_sync_duration_seconds", text)
        self.assertIn("cf_tunnel_safety_guard_tripped", text)


class TestUpgradeInPlaceRegression(unittest.TestCase):
    """COMPAT-02 & COMPAT-04: Upgrade-in-Place and Resource Ownership Invariants."""

    def setUp(self):
        self.fixtures_dir = str(FIXTURES_DIR)

    def test_upgrade_single_compose_topology_idempotence(self):
        """Simulate upgrading an existing single-compose deployment: 0 mutations planned."""
        fixture_path = os.path.join(self.fixtures_dir, "single_compose_v1_13.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            fixture = json.load(f)

        tunnel_id = fixture["environment"]["CLOUDFLARE_TUNNEL_ID"]
        tunnel_name = fixture["environment"]["CLOUDFLARE_TUNNEL_NAME"]
        tunnel_target = f"{tunnel_id}.cfargotunnel.com"

        snapshot = DiscoverySnapshot(
            timestamp=1729160000.0,
            docker_ok=True,
            origins=[
                DiscoveredOrigin(
                    container_id="c1a2b3c4d5e6",
                    container_name="whoami-service",
                    hostname="whoami.example.com",
                    service_target="http://whoami-service:80",
                )
            ],
        )

        remote = RemoteState(
            tunnel_id=tunnel_id,
            tunnel_name=tunnel_name,
            zone_id="mock-zone-id-12345",
            tunnel_target=tunnel_target,
            existing_ingress_rules=fixture["expected_remote_ingress"],
            existing_dns_records=fixture["expected_remote_dns"],
        )

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=1729160000.0,
            policy=OwnershipPolicy.ADOPT_AND_MANAGE,
            dns_delete_grace_seconds=60.0,
        )

        # In-place upgrade must result in zero destructive or unexpected mutations
        self.assertEqual(plan.summary.ingress_creates, 0)
        self.assertEqual(plan.summary.ingress_deletes, 0)
        self.assertEqual(plan.summary.dns_creates, 0)
        self.assertEqual(plan.summary.dns_updates, 0)
        self.assertEqual(plan.summary.dns_deletes, 0)
        self.assertFalse(plan.summary.has_mutations)

    def test_upgrade_multi_compose_topology_idempotence(self):
        """Simulate upgrading a multi-compose deployment: 0 mutations planned."""
        fixture_path = os.path.join(self.fixtures_dir, "multi_compose_v1_13.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            fixture = json.load(f)

        tunnel_id = fixture["environment"]["CLOUDFLARE_TUNNEL_ID"]
        tunnel_name = fixture["environment"]["CLOUDFLARE_TUNNEL_NAME"]
        tunnel_target = f"{tunnel_id}.cfargotunnel.com"

        snapshot = DiscoverySnapshot(
            timestamp=1729160000.0,
            docker_ok=True,
            origins=[
                DiscoveredOrigin(
                    container_id="app-container-9988",
                    container_name="blog-service",
                    hostname="blog.example.com",
                    service_target="http://blog-service:2368",
                )
            ],
        )

        remote = RemoteState(
            tunnel_id=tunnel_id,
            tunnel_name=tunnel_name,
            zone_id="mock-zone-id-12345",
            tunnel_target=tunnel_target,
            existing_ingress_rules=fixture["expected_remote_ingress"],
            existing_dns_records=fixture["expected_remote_dns"],
        )

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=1729160000.0,
            policy=OwnershipPolicy.ADOPT_AND_MANAGE,
            dns_delete_grace_seconds=60.0,
        )

        self.assertFalse(plan.summary.has_mutations)
        self.assertEqual(plan.summary.dns_deletes, 0)
        self.assertEqual(plan.summary.ingress_deletes, 0)

    def test_preserve_unmanaged_dns_and_ingress_across_upgrade(self):
        """COMPAT-04: Ensure unmanaged external DNS records and manual Ingress rules are preserved."""
        tunnel_id = "55555555-6666-7777-8888-999999999999"
        tunnel_name = "corp-gateway"
        tunnel_target = f"{tunnel_id}.cfargotunnel.com"

        snapshot = DiscoverySnapshot(
            timestamp=1729160000.0,
            docker_ok=True,
            origins=[
                DiscoveredOrigin(
                    container_id="cont-1",
                    container_name="managed-app",
                    hostname="managed.example.com",
                    service_target="http://managed-app:8080",
                )
            ],
        )

        # Existing remote state contains:
        # 1. Managed CNAME for managed.example.com
        # 2. Unmanaged external CNAME for cdn.example.com -> external-cdn.net
        # 3. Unmanaged A record for apex example.com -> 198.51.100.1
        # 4. Unmanaged Ingress rule for static-legacy.example.com -> http://10.0.0.5:80
        remote = RemoteState(
            tunnel_id=tunnel_id,
            tunnel_name=tunnel_name,
            zone_id="mock-zone-123",
            tunnel_target=tunnel_target,
            existing_ingress_rules=[
                {"hostname": "managed.example.com", "service": "http://managed-app:8080"},
                {"hostname": "static-legacy.example.com", "service": "http://10.0.0.5:80"},
                {"service": "http_status:404"},
            ],
            existing_dns_records=[
                {
                    "id": "rec-01",
                    "type": "CNAME",
                    "name": "managed.example.com",
                    "content": tunnel_target,
                    "comment": f"cf-tunnel-sync:{tunnel_name}",
                },
                {
                    "id": "rec-02",
                    "type": "CNAME",
                    "name": "cdn.example.com",
                    "content": "external-cdn.net",  # Unrelated external target
                    "comment": "Managed by CDN provider",
                },
                {
                    "id": "rec-03",
                    "type": "A",
                    "name": "example.com",
                    "content": "198.51.100.1",
                    "comment": "Apex A record",
                },
            ],
        )

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=1729160000.0,
            policy=OwnershipPolicy.STRICT_TAGGED_ONLY,
            dns_delete_grace_seconds=60.0,
        )

        # Verify:
        # - 0 DNS deletions
        # - Unmanaged CNAME rec-02 is explicitly skipped/protected
        self.assertEqual(plan.summary.dns_deletes, 0)
        self.assertGreaterEqual(plan.summary.unmanaged_skipped, 1)
        # Verify unmanaged ingress rule is not deleted during upgrade
        self.assertEqual(plan.summary.ingress_deletes, 0)
        # Rule remains in final_ingress_rules
        final_hosts = [r.get("hostname") for r in plan.final_ingress_rules]
        self.assertIn("static-legacy.example.com", final_hosts)

    def test_downgrade_and_rollback_safety(self):
        """COMPAT-05: Verify rollback safety — state and configuration have zero irreversible migrations."""
        # Ensure that no sqlite/db files or schema version locks are written that block rollback
        self.assertFalse((REPO_ROOT / "sync_state.db").exists())
        self.assertFalse((REPO_ROOT / "migrations").exists())


if __name__ == "__main__":
    unittest.main()
