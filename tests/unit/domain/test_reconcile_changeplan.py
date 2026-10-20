"""
Hermetic Unit & Integration Tests for Issue #46:
Pure ChangePlan Engine & Safe Resource Ownership Model (Findings A01 & F02)
"""

import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import app
from reconcile import (
    BlastRadiusExceededError,
    ChangePlan,
    ChangePlanSummary,
    DiscoveredOrigin,
    DiscoverySnapshot,
    DnsActionType,
    IngressActionType,
    OwnershipPolicy,
    OwnershipStatus,
    OwnershipTagging,
    PlannedDnsChange,
    PlannedIngressChange,
    RemoteState,
    compute_change_plan,
    execute_change_plan,
)


class TestPureChangePlanEngine(unittest.TestCase):
    """Hermetic unit tests for the pure reconciliation engine and safe ownership model."""

    def setUp(self):
        self.tunnel_name = "test-tunnel"
        self.tunnel_id = "tun-abcdef123"
        self.zone_id = "zone-98765"
        self.tunnel_target = f"{self.tunnel_id}.cfargotunnel.com"
        self.tagger = OwnershipTagging(tunnel_name=self.tunnel_name)
        self.expected_comment = f"cf-tunnel-sync:{self.tunnel_name}"

    def test_ownership_tagging_classification(self):
        """TC-46-01: OwnershipTagging classifies records accurately according to comment & target."""
        # Unrelated: Not a CNAME
        rec_a = {"id": "1", "name": "a.example.com", "type": "A", "content": "1.2.3.4"}
        self.assertEqual(
            self.tagger.parse_status(rec_a, self.tunnel_target, is_active_local=True),
            OwnershipStatus.UNRELATED,
        )

        # Unrelated: CNAME pointing elsewhere
        rec_other = {"id": "2", "name": "other.example.com", "type": "CNAME", "content": "external.host.com"}
        self.assertEqual(
            self.tagger.parse_status(rec_other, self.tunnel_target, is_active_local=True),
            OwnershipStatus.UNRELATED,
        )

        # Owned: CNAME matching tunnel target and tagger comment
        rec_owned = {
            "id": "3",
            "name": "owned.example.com",
            "type": "CNAME",
            "content": self.tunnel_target,
            "comment": self.expected_comment,
        }
        self.assertEqual(
            self.tagger.parse_status(rec_owned, self.tunnel_target, is_active_local=True),
            OwnershipStatus.OWNED,
        )

        # Foreign Tunnel: CNAME matching tunnel target but tagger comment belongs to another tunnel
        rec_foreign = {
            "id": "4",
            "name": "foreign.example.com",
            "type": "CNAME",
            "content": self.tunnel_target,
            "comment": "cf-tunnel-sync:other-tunnel-instance",
        }
        self.assertEqual(
            self.tagger.parse_status(rec_foreign, self.tunnel_target, is_active_local=True),
            OwnershipStatus.FOREIGN_TUNNEL,
        )

        # Adopted: Active local origin pointing to tunnel target with empty comment
        rec_unmanaged = {
            "id": "5",
            "name": "adopt.example.com",
            "type": "CNAME",
            "content": self.tunnel_target,
            "comment": "",
        }
        self.assertEqual(
            self.tagger.parse_status(rec_unmanaged, self.tunnel_target, is_active_local=True),
            OwnershipStatus.ADOPTED,
        )

        # Unmanaged: Offline origin pointing to tunnel target with empty comment
        self.assertEqual(
            self.tagger.parse_status(rec_unmanaged, self.tunnel_target, is_active_local=False),
            OwnershipStatus.UNMANAGED,
        )

    def test_dns_decision_matrix_active_origins(self):
        """TC-46-02: Decision matrix for active discovered origins: CREATE, NOOP, UPDATE, PROTECT."""
        now = 1000.0
        snapshot = DiscoverySnapshot(
            timestamp=now,
            docker_ok=True,
            origins=[
                DiscoveredOrigin(
                    container_id="c1",
                    container_name="app-new",
                    hostname="new.example.com",
                    service_target="http://app-new:80",
                ),
                DiscoveredOrigin(
                    container_id="c2",
                    container_name="app-synced",
                    hostname="synced.example.com",
                    service_target="http://app-synced:80",
                ),
                DiscoveredOrigin(
                    container_id="c3",
                    container_name="app-adopt",
                    hostname="adopt.example.com",
                    service_target="http://app-adopt:80",
                ),
                DiscoveredOrigin(
                    container_id="c4",
                    container_name="app-foreign",
                    hostname="foreign.example.com",
                    service_target="http://app-foreign:80",
                ),
            ],
        )

        existing_dns = [
            # synced.example.com matches target, proxied, and comment -> NOOP
            {
                "id": "rec-synced",
                "name": "synced.example.com",
                "type": "CNAME",
                "content": self.tunnel_target,
                "proxied": True,
                "ttl": 1,
                "comment": self.expected_comment,
            },
            # adopt.example.com has empty comment -> ADOPTED -> UPDATE
            {
                "id": "rec-adopt",
                "name": "adopt.example.com",
                "type": "CNAME",
                "content": self.tunnel_target,
                "proxied": True,
                "ttl": 1,
                "comment": "",
            },
            # foreign.example.com has foreign tunnel tag -> PROTECT
            {
                "id": "rec-foreign",
                "name": "foreign.example.com",
                "type": "CNAME",
                "content": self.tunnel_target,
                "proxied": True,
                "ttl": 1,
                "comment": "cf-tunnel-sync:foreign-cluster",
            },
        ]

        remote = RemoteState(
            tunnel_id=self.tunnel_id,
            tunnel_name=self.tunnel_name,
            zone_id=self.zone_id,
            tunnel_target=self.tunnel_target,
            existing_ingress_rules=[],
            existing_dns_records=existing_dns,
        )

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=now,
            policy=OwnershipPolicy.ADOPT_AND_MANAGE,
        )

        dns_actions = {c.hostname: c.action for c in plan.dns_changes}
        self.assertEqual(dns_actions["new.example.com"], DnsActionType.CREATE)
        self.assertEqual(dns_actions["synced.example.com"], DnsActionType.NOOP)
        self.assertEqual(dns_actions["adopt.example.com"], DnsActionType.UPDATE)
        self.assertEqual(dns_actions["foreign.example.com"], DnsActionType.PROTECT)

        # Validate that adopt action updates target_comment
        adopt_change = next(c for c in plan.dns_changes if c.hostname == "adopt.example.com")
        self.assertEqual(adopt_change.target_comment, self.expected_comment)

    def test_safe_ownership_unmanaged_offline_record_is_protected(self):
        """TC-46-03: Finding F02: Manual unmanaged CNAME pointing to tunnel is never silently deleted."""
        now = 1000.0
        snapshot = DiscoverySnapshot(timestamp=now, docker_ok=True, origins=[])

        existing_dns = [
            {
                "id": "rec-manual",
                "name": "manual-cname.example.com",
                "type": "CNAME",
                "content": self.tunnel_target,
                "proxied": True,
                "ttl": 1,
                "comment": "",  # Unmanaged manual record
            }
        ]

        remote = RemoteState(
            tunnel_id=self.tunnel_id,
            tunnel_name=self.tunnel_name,
            zone_id=self.zone_id,
            tunnel_target=self.tunnel_target,
            existing_ingress_rules=[],
            existing_dns_records=existing_dns,
        )

        # Under default adopt_and_manage policy:
        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=now,
            policy=OwnershipPolicy.ADOPT_AND_MANAGE,
        )

        self.assertEqual(len(plan.dns_changes), 1)
        change = plan.dns_changes[0]
        self.assertEqual(change.hostname, "manual-cname.example.com")
        self.assertEqual(change.action, DnsActionType.PROTECT)
        self.assertEqual(change.ownership_status, OwnershipStatus.UNMANAGED)
        self.assertIn("unmanaged CNAME protected", change.reason)
        self.assertFalse(plan.summary.is_destructive)
        self.assertEqual(plan.summary.dns_deletes, 0)

    def test_dns_tombstoning_lifecycle(self):
        """TC-46-04: Owned records enter tombstone window on disappearance and delete after expiry."""
        t0 = 1000.0
        grace_period = 300.0

        snapshot_empty = DiscoverySnapshot(timestamp=t0, docker_ok=True, origins=[])

        owned_dns = [
            {
                "id": "rec-owned-disappeared",
                "name": "vanished.example.com",
                "type": "CNAME",
                "content": self.tunnel_target,
                "proxied": True,
                "ttl": 1,
                "comment": self.expected_comment,
            }
        ]

        remote = RemoteState(
            tunnel_id=self.tunnel_id,
            tunnel_name=self.tunnel_name,
            zone_id=self.zone_id,
            tunnel_target=self.tunnel_target,
            existing_ingress_rules=[
                {"hostname": "vanished.example.com", "service": "http://vanished:80"},
                {"service": "http_status:404"},
            ],
            existing_dns_records=owned_dns,
        )

        # 1. First sync without container: gets tombstoned (NOOP)
        plan1 = compute_change_plan(
            snapshot=snapshot_empty,
            remote=remote,
            tombstones={},
            now=t0,
            dns_delete_grace_seconds=grace_period,
        )
        self.assertIn("vanished.example.com", plan1.tombstones_to_set)
        self.assertEqual(plan1.tombstones_to_set["vanished.example.com"], t0)
        vanished_dns_change1 = next(c for c in plan1.dns_changes if c.hostname == "vanished.example.com")
        self.assertEqual(vanished_dns_change1.action, DnsActionType.NOOP)
        self.assertEqual(plan1.summary.dns_deletes, 0)

        # 2. Intermediate sync at t0 + 100s: still in grace period (NOOP)
        tombstones_active = {"vanished.example.com": t0}
        plan2 = compute_change_plan(
            snapshot=snapshot_empty,
            remote=remote,
            tombstones=tombstones_active,
            now=t0 + 100.0,
            dns_delete_grace_seconds=grace_period,
        )
        vanished_dns_change2 = next(c for c in plan2.dns_changes if c.hostname == "vanished.example.com")
        self.assertEqual(vanished_dns_change2.action, DnsActionType.NOOP)
        self.assertEqual(plan2.summary.dns_deletes, 0)

        # 3. Final sync after expiry at t0 + 350s: planned for DELETE
        plan3 = compute_change_plan(
            snapshot=snapshot_empty,
            remote=remote,
            tombstones=tombstones_active,
            now=t0 + 350.0,
            dns_delete_grace_seconds=grace_period,
        )
        vanished_dns_change3 = next(c for c in plan3.dns_changes if c.hostname == "vanished.example.com")
        self.assertEqual(vanished_dns_change3.action, DnsActionType.DELETE)
        self.assertIn("vanished.example.com", plan3.tombstones_to_clear)
        self.assertEqual(plan3.summary.dns_deletes, 1)
        self.assertTrue(plan3.summary.is_destructive)

    def test_ingress_reconciliation_and_catchall_invariant(self):
        """TC-46-05: Ingress rules are diffed cleanly and trailing 404 rule is always preserved."""
        snapshot = DiscoverySnapshot(
            timestamp=1000.0,
            docker_ok=True,
            origins=[
                DiscoveredOrigin(
                    container_id="c1",
                    container_name="web",
                    hostname="web.example.com",
                    service_target="http://web:8080",
                    origin_request={"noTLSVerify": True},
                ),
            ],
        )

        remote = RemoteState(
            tunnel_id=self.tunnel_id,
            tunnel_name=self.tunnel_name,
            zone_id=self.zone_id,
            tunnel_target=self.tunnel_target,
            existing_ingress_rules=[
                {"hostname": "web.example.com", "service": "http://web:8080", "originRequest": {"noTLSVerify": False}},
                {"service": "http_status:404"},
            ],
            existing_dns_records=[],
        )

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=1000.0,
        )

        # Ingress was updated due to originRequest modification
        self.assertEqual(len(plan.ingress_changes), 1)
        self.assertEqual(plan.ingress_changes[0].action, IngressActionType.UPDATE)

        # Final ingress rules must contain the service rule and the trailing 404 rule
        self.assertEqual(len(plan.final_ingress_rules), 2)
        self.assertEqual(plan.final_ingress_rules[0]["hostname"], "web.example.com")
        self.assertEqual(plan.final_ingress_rules[0]["service"], "http://web:8080")
        self.assertEqual(plan.final_ingress_rules[0]["originRequest"], {"noTLSVerify": True})
        self.assertEqual(plan.final_ingress_rules[1]["service"], "http_status:404")

    def test_blast_radius_guard_aborts_excessive_deletions(self):
        """TC-46-06: execute_change_plan aborts when total deletions exceed MAX_DELETIONS_PER_RUN."""
        plan = ChangePlan(
            plan_id="plan-test-blast",
            timestamp=1000.0,
            tunnel_id=self.tunnel_id,
            zone_id=self.zone_id,
            ingress_changes=[],
            dns_changes=[
                PlannedDnsChange(
                    action=DnsActionType.DELETE,
                    hostname=f"app{i}.example.com",
                    record_id=f"rec-{i}",
                    ownership_status=OwnershipStatus.OWNED,
                    reason="expired",
                )
                for i in range(5)
            ],
            final_ingress_rules=[{"service": "http_status:404"}],
            summary=ChangePlanSummary(
                total_services_discovered=0,
                dns_deletes=5,
                has_mutations=True,
                is_destructive=True,
            ),
        )

        mock_cf_api = MagicMock()
        mock_log = MagicMock()

        # Configured max_deletions = 2, plan has 5 -> should raise BlastRadiusExceededError
        with self.assertRaises(BlastRadiusExceededError):
            execute_change_plan(
                plan=plan,
                token="dummy-token",
                account_id="dummy-acc",
                cf_api_fn=mock_cf_api,
                dry_run=False,
                max_deletions=2,
                log_fn=mock_log,
            )

        # Ensure no mutations occurred
        self.assertEqual(mock_cf_api.call_count, 0)
        self.assertTrue(any("BLAST RADIUS GUARD" in call.args[0] for call in mock_log.call_args_list))

    def test_dry_run_mode_produces_zero_mutations(self):
        """TC-46-07: execute_change_plan with dry_run=True performs zero Cloudflare API mutations."""
        plan = ChangePlan(
            plan_id="plan-test-dryrun",
            timestamp=1000.0,
            tunnel_id=self.tunnel_id,
            zone_id=self.zone_id,
            ingress_changes=[
                PlannedIngressChange(
                    action=IngressActionType.CREATE,
                    hostname="dry.example.com",
                    service="http://dry:80",
                    reason="new",
                )
            ],
            dns_changes=[
                PlannedDnsChange(
                    action=DnsActionType.CREATE,
                    hostname="dry.example.com",
                    target_content=self.tunnel_target,
                    target_comment=self.expected_comment,
                    ownership_status=OwnershipStatus.OWNED,
                    reason="new",
                )
            ],
            final_ingress_rules=[
                {"hostname": "dry.example.com", "service": "http://dry:80"},
                {"service": "http_status:404"},
            ],
            summary=ChangePlanSummary(
                total_services_discovered=1,
                ingress_creates=1,
                dns_creates=1,
                has_mutations=True,
            ),
        )

        mock_cf_api = MagicMock()
        mock_log = MagicMock()

        res = execute_change_plan(
            plan=plan,
            token="dummy-token",
            account_id="dummy-acc",
            cf_api_fn=mock_cf_api,
            dry_run=True,
            log_fn=mock_log,
        )

        self.assertFalse(res["executed"])
        self.assertTrue(res["dry_run"])
        self.assertEqual(mock_cf_api.call_count, 0)
        self.assertTrue(any("[DRY-RUN]" in call.args[0] for call in mock_log.call_args_list))

    def test_preview_api_endpoint(self):
        """TC-46-08: GET /api/v1/sync/preview returns structured ChangePlan without mutating state."""
        client = TestClient(app.app)
        response = client.get("/api/v1/sync/preview")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("plan", data)
        plan = data["plan"]
        self.assertIn("plan_id", plan)
        self.assertIn("summary", plan)
        self.assertIn("final_ingress_rules", plan)


if __name__ == "__main__":
    unittest.main()
