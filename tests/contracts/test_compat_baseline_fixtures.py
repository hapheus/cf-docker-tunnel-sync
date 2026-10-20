"""Automated baseline and golden fixtures regression tests (Issue #83 - COMPAT-01).

Validates that supported v1.13.0 deployments (single-compose, multi-compose,
custom networks, legacy label aliases, and access policies) produce zero
unexpected mutations and match golden baseline expectations.
"""

import json
import unittest

from reconcile import (
    DiscoveredOrigin,
    DiscoverySnapshot,
    OwnershipPolicy,
    OwnershipStatus,
    OwnershipTagging,
    RemoteState,
    compute_change_plan,
)
from tests.paths import FIXTURES_DIR


class TestCompatBaselineFixtures(unittest.TestCase):
    """Test suite validating golden fixtures against reconciliation engine."""

    def load_fixture(self, filename: str) -> dict:
        fixture_path = FIXTURES_DIR / filename
        self.assertTrue(fixture_path.exists(), f"Fixture file {filename} not found")
        with open(fixture_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_golden_v1_13_0_single_compose_idempotence(self):
        """Single-compose deployment from v1.13.0 baseline reconciles with 0 mutations."""
        data = self.load_fixture("golden_v1_13_0_single_compose.json")
        origins = [DiscoveredOrigin(**o) for o in data["discovered_origins"]]
        snapshot = DiscoverySnapshot(timestamp=100.0, docker_ok=True, origins=origins)
        remote = RemoteState(**data["remote_state"])

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=100.0,
            policy=OwnershipPolicy.ADOPT_AND_MANAGE,
            dns_delete_grace_seconds=60.0,
        )

        self.assertFalse(plan.summary.has_mutations, "Single compose produced unexpected mutations")
        self.assertEqual(plan.summary.ingress_creates, 0)
        self.assertEqual(plan.summary.ingress_deletes, 0)
        self.assertEqual(plan.summary.dns_creates, 0)
        self.assertEqual(plan.summary.dns_deletes, 0)

    def test_golden_v1_13_0_multi_compose_idempotence(self):
        """Multi-compose deployment with custom networks reconciles with 0 mutations."""
        data = self.load_fixture("golden_v1_13_0_multi_compose.json")
        origins = [DiscoveredOrigin(**o) for o in data["discovered_origins"]]
        snapshot = DiscoverySnapshot(timestamp=100.0, docker_ok=True, origins=origins)
        remote = RemoteState(**data["remote_state"])

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=100.0,
            policy=OwnershipPolicy.ADOPT_AND_MANAGE,
            dns_delete_grace_seconds=60.0,
        )

        self.assertFalse(plan.summary.has_mutations, "Multi compose produced unexpected mutations")
        self.assertEqual(plan.summary.ingress_creates, 0)
        self.assertEqual(plan.summary.dns_creates, 0)

    def test_golden_v1_13_0_legacy_aliases_support(self):
        """Legacy label aliases (tunnel.hostname, tunnel.port, cloudflared.proto) map correctly."""
        data = self.load_fixture("golden_v1_13_0_legacy_aliases.json")
        origins = [DiscoveredOrigin(**o) for o in data["discovered_origins"]]
        snapshot = DiscoverySnapshot(timestamp=100.0, docker_ok=True, origins=origins)
        remote = RemoteState(**data["remote_state"])

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=100.0,
            policy=OwnershipPolicy.ADOPT_AND_MANAGE,
            dns_delete_grace_seconds=60.0,
        )

        self.assertFalse(plan.summary.has_mutations, "Legacy aliases produced unexpected mutations")
        self.assertEqual(plan.summary.ingress_creates, 0)
        self.assertEqual(plan.summary.dns_creates, 0)

    def test_golden_v1_13_0_access_policy_support(self):
        """Access policy tags and advanced originRequest labels reconcile cleanly."""
        data = self.load_fixture("golden_v1_13_0_access_policy.json")
        origins = [DiscoveredOrigin(**o) for o in data["discovered_origins"]]
        snapshot = DiscoverySnapshot(timestamp=100.0, docker_ok=True, origins=origins)
        remote = RemoteState(**data["remote_state"])

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=100.0,
            policy=OwnershipPolicy.ADOPT_AND_MANAGE,
            dns_delete_grace_seconds=60.0,
        )

        self.assertFalse(plan.summary.has_mutations, "Access policy tagging produced unexpected mutations")
        self.assertEqual(plan.summary.ingress_creates, 0)
        self.assertEqual(plan.summary.dns_creates, 0)

    def test_container_stop_and_restart_grace_period(self):
        """Stopping a container initiates tombstone and does not immediately delete remote route."""
        data = self.load_fixture("golden_v1_13_0_single_compose.json")
        empty_snapshot = DiscoverySnapshot(timestamp=100.0, docker_ok=True, origins=[])
        remote = RemoteState(**data["remote_state"])

        # Reconcile immediately after stop: sets tombstone, 0 deletes
        plan = compute_change_plan(
            snapshot=empty_snapshot,
            remote=remote,
            tombstones={},
            now=100.0,
            policy=OwnershipPolicy.ADOPT_AND_MANAGE,
            dns_delete_grace_seconds=60.0,
        )

        self.assertEqual(plan.summary.dns_deletes, 0, "Grace period must protect DNS from immediate deletion")
        self.assertEqual(plan.summary.ingress_deletes, 0, "Grace period must protect Ingress from immediate deletion")
        self.assertIn("whoami.example.com", plan.tombstones_to_set)

        # Restoring container restores zero mutation against original remote state
        origins = [DiscoveredOrigin(**o) for o in data["discovered_origins"]]
        full_snapshot = DiscoverySnapshot(timestamp=105.0, docker_ok=True, origins=origins)
        plan_restart = compute_change_plan(
            snapshot=full_snapshot,
            remote=remote,
            tombstones=plan.tombstones_to_set,
            now=105.0,
            policy=OwnershipPolicy.ADOPT_AND_MANAGE,
            dns_delete_grace_seconds=60.0,
        )
        self.assertFalse(plan_restart.summary.has_mutations)
        self.assertEqual(plan_restart.summary.ingress_creates, 0)
        self.assertEqual(plan_restart.summary.dns_creates, 0)

    def test_foreign_and_unrelated_dns_protection(self):
        """Validates that foreign DNS records are strictly preserved and never mutated."""
        tagger = OwnershipTagging(tunnel_name="primary-tunnel")
        tunnel_target = "00000000-0000-0000-0000-000000000001.cfargotunnel.com"
        tagger = OwnershipTagging(tunnel_name="prod-gateway")

        foreign_record = {
            "name": "foreign.example.com",
            "type": "CNAME",
            "content": "different-target.cfargotunnel.com",
            "comment": "manual-external",
        }
        self.assertEqual(
            tagger.parse_status(foreign_record, tunnel_target, is_active_local=False),
            OwnershipStatus.UNRELATED,
        )

        foreign_tunnel_record = {
            "name": "other-tunnel.example.com",
            "type": "CNAME",
            "content": tunnel_target,
            "comment": "cf-tunnel-sync:other-tunnel",
        }
        self.assertEqual(
            tagger.parse_status(foreign_tunnel_record, tunnel_target, is_active_local=False),
            OwnershipStatus.FOREIGN_TUNNEL,
        )


if __name__ == "__main__":
    unittest.main()
