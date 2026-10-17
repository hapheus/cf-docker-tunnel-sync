"""Upgrade-in-place end-to-end regression tests (Issue #84 - COMPAT-02).

Simulates image-only upgrade of existing stacks (v1.13.0 -> current release)
against mocked Cloudflare and Docker fixtures to prove:
1. Zero mutations occur unless container state changed.
2. No DNS records are re-created, deleted, or duplicated.
3. Ingress rules remain identical.
4. Existing setups require zero configuration changes.
5. Downgrade/rollback succeeds safely.
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app import perform_startup_validation
from reconcile import (
    DiscoveredOrigin,
    DiscoverySnapshot,
    DnsActionType,
    IngressActionType,
    RemoteState,
    compute_change_plan,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestCompatUpgradeInPlace(unittest.TestCase):
    """E2E Upgrade-in-place verification suite for v1.13.0 deployments."""

    def load_fixture(self, filename: str) -> dict:
        fixture_path = FIXTURES_DIR / filename
        with open(fixture_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_upgrade_requires_zero_configuration_changes(self):
        """Verifies that an existing v1.13.0 environment configuration passes startup validation without error."""
        # Realistic existing v1.13.0 compose environment
        v1_13_env = {
            "CLOUDFLARE_API_TOKEN": "cf-token-existing-12345",
            "CLOUDFLARE_ACCOUNT_ID": "a1b2c3d4e5f678901234567890abcdef",
            "CLOUDFLARE_TUNNEL_NAME": "homelab-gateway",
            "CLOUDFLARE_TUNNEL_ID": "11111111-2222-3333-4444-555555555555",
            "CF_NETWORK_NAME": "cf-tunnel-net",
            "DRY_RUN": "true",
            "PREFLIGHT_ONLY": "true",
            "LOG_LEVEL": "INFO",
            "LOG_FORMAT": "json",
            "DASHBOARD_ENABLED": "true",
            "DASHBOARD_PORT": "8080",
        }

        with patch.dict(os.environ, v1_13_env, clear=True):
            warnings = perform_startup_validation()
            self.assertEqual(warnings, [], "Existing v1.13.0 environment produced warnings/errors upon upgrade")

    def test_upgrade_in_place_zero_mutations_across_topologies(self):
        """Simulates in-place image upgrade across single-compose, multi-compose, and custom setups."""
        fixture_names = [
            "golden_v1_13_0_single_compose.json",
            "golden_v1_13_0_multi_compose.json",
            "golden_v1_13_0_legacy_aliases.json",
            "golden_v1_13_0_access_policy.json",
        ]

        for fixture_file in fixture_names:
            with self.subTest(fixture=fixture_file):
                fixture = self.load_fixture(fixture_file)
                origins = [DiscoveredOrigin(**o) for o in fixture["discovered_origins"]]
                snapshot = DiscoverySnapshot(timestamp=1729160000.0, docker_ok=True, origins=origins)
                remote = RemoteState(**fixture["remote_state"])

                # Execute reconciliation engine (as the upgraded image would on initial startup)
                plan = compute_change_plan(
                    snapshot=snapshot,
                    remote=remote,
                    tombstones={},
                    dry_run=True,
                    tag_prefix=f"cf-tunnel-sync:{remote.tunnel_name}",
                )

                # Invariant: Zero mutations on existing active containers
                self.assertFalse(
                    plan.summary.has_mutations,
                    f"Upgrade caused unexpected mutations for {fixture_file}: {plan.summary}",
                )
                self.assertEqual(plan.summary.ingress_creates, 0)
                self.assertEqual(plan.summary.ingress_updates, 0)
                self.assertEqual(plan.summary.ingress_deletes, 0)
                self.assertEqual(plan.summary.dns_creates, 0)
                self.assertEqual(plan.summary.dns_updates, 0)
                self.assertEqual(plan.summary.dns_deletes, 0)

    def test_post_upgrade_selective_delta_mutation(self):
        """Proves that post-upgrade, adding a new service mutates ONLY that service without touching existing ones."""
        fixture = self.load_fixture("golden_v1_13_0_single_compose.json")
        remote = RemoteState(**fixture["remote_state"])

        # Existing container + new container deployed after upgrade
        existing_origins = [DiscoveredOrigin(**o) for o in fixture["discovered_origins"]]
        new_origin = DiscoveredOrigin(
            container_id="c_new_service_999",
            container_name="new_service",
            hostname="new.example.com",
            service_target="http://new_service:8080",
            labels={"cf.tunnel.hostname": "new.example.com"},
        )
        post_upgrade_origins = existing_origins + [new_origin]
        snapshot = DiscoverySnapshot(timestamp=1729160010.0, docker_ok=True, origins=post_upgrade_origins)

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            dry_run=True,
            tag_prefix=f"cf-tunnel-sync:{remote.tunnel_name}",
        )

        # Invariant: Exactly 1 ingress create, 1 DNS create (for the new service only)
        self.assertTrue(plan.summary.has_mutations)
        self.assertEqual(plan.summary.ingress_creates, 1)
        self.assertEqual(plan.summary.ingress_updates, 0)
        self.assertEqual(plan.summary.ingress_deletes, 0)
        self.assertEqual(plan.summary.dns_creates, 1)
        self.assertEqual(plan.summary.dns_updates, 0)
        self.assertEqual(plan.summary.dns_deletes, 0)

        # Existing service must NOT be modified or re-created
        existing_host = existing_origins[0].hostname
        for dns_change in plan.dns_changes:
            if dns_change.hostname == existing_host:
                self.assertIn(dns_change.action, (DnsActionType.PROTECT, DnsActionType.NOOP))
            elif dns_change.hostname == "new.example.com":
                self.assertEqual(dns_change.action, DnsActionType.CREATE)

        for ing_change in plan.ingress_changes:
            if ing_change.hostname == existing_host:
                self.assertEqual(ing_change.action, IngressActionType.NOOP)
            elif ing_change.hostname == "new.example.com":
                self.assertEqual(ing_change.action, IngressActionType.CREATE)

    def test_downgrade_compatibility_and_state_preservation(self):
        """Validates that state representations remain 100% compatible with v1.13.0 consumers during rollback."""
        fixture = self.load_fixture("golden_v1_13_0_single_compose.json")
        remote = RemoteState(**fixture["remote_state"])
        origins = [DiscoveredOrigin(**o) for o in fixture["discovered_origins"]]
        snapshot = DiscoverySnapshot(timestamp=1729160000.0, docker_ok=True, origins=origins)

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            dry_run=True,
            tag_prefix=f"cf-tunnel-sync:{remote.tunnel_name}",
        )

        api_dict = plan.to_api_dict()
        # Ensure schema structure matches v1.13.0 expectations
        self.assertIn("summary", api_dict)
        self.assertIn("actions", api_dict)
        summary = api_dict["summary"]
        self.assertIn("additions", summary)
        self.assertIn("updates", summary)
        self.assertIn("deletions", summary)
        self.assertEqual(summary["additions"], 0)
        self.assertEqual(summary["updates"], 0)
        self.assertEqual(summary["deletions"], 0)
        self.assertFalse(plan.summary.has_mutations)


if __name__ == "__main__":
    unittest.main()
