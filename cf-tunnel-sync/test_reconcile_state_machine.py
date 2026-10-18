"""Comprehensive state-machine tests for reconciliation lifecycle transitions (SAFE-05 / Issue #105).

Models complete container lifecycle:
1. Initial discovery -> CREATE
2. Steady-state -> NOOP
3. Origin modification -> UPDATE
4. Transient stop -> TOMBSTONE (NOOP)
5. Recovery before grace period -> TOMBSTONE CLEARED (NOOP)
6. Permanent removal after grace period -> DELETE
7. Rapid event reordering & hostname conflicts -> Deterministic convergence
"""

import unittest

from reconcile import (
    DnsActionType,
    IngressActionType,
    RemoteState,
    build_discovery_snapshot,
    compute_change_plan,
)


class TestReconcileStateMachine(unittest.TestCase):
    def setUp(self):
        self.tunnel_id = "tun-lifecycle-123"
        self.tunnel_name = "test-gateway"
        self.zone_id = "zone-lifecycle-456"
        self.tunnel_target = f"{self.tunnel_id}.cfargotunnel.com"
        self.expected_comment = f"cf-tunnel-sync:{self.tunnel_name}"

    def _remote_state(self, ingress_rules=None, dns_records=None) -> RemoteState:
        rules = list(ingress_rules or [])
        if not any(r.get("service") == "http_status:404" for r in rules):
            rules.append({"service": "http_status:404"})
        return RemoteState(
            tunnel_id=self.tunnel_id,
            tunnel_name=self.tunnel_name,
            zone_id=self.zone_id,
            tunnel_target=self.tunnel_target,
            existing_ingress_rules=rules,
            existing_dns_records=list(dns_records or []),
        )

    def test_transition_1_initial_discovery_creates_ingress_and_tagged_dns(self):
        """Lifecycle 1: New container discovered -> Ingress CREATE + DNS CREATE with tag."""
        snapshot = build_discovery_snapshot(
            services=[{"hostname": "app.example.com", "service": "http://app:8080"}],
            all_containers=[{"Names": ["/app"]}],
            docker_ok=True,
        )
        remote = self._remote_state()

        plan = compute_change_plan(snapshot=snapshot, remote=remote, tombstones={}, now=100.0)

        # Ingress CREATE
        ing_creates = [c for c in plan.ingress_changes if c.action == IngressActionType.CREATE]
        self.assertEqual(len(ing_creates), 1)
        self.assertEqual(ing_creates[0].hostname, "app.example.com")
        self.assertEqual(ing_creates[0].service, "http://app:8080")

        # DNS CREATE with comment tag
        dns_creates = [c for c in plan.dns_changes if c.action == DnsActionType.CREATE]
        self.assertEqual(len(dns_creates), 1)
        self.assertEqual(dns_creates[0].hostname, "app.example.com")
        self.assertEqual(dns_creates[0].target_content, self.tunnel_target)
        self.assertEqual(dns_creates[0].target_comment, self.expected_comment)
        self.assertTrue(plan.summary.has_mutations)
        self.assertFalse(plan.summary.is_destructive)

    def test_transition_2_steady_state_converges_to_noop(self):
        """Lifecycle 2: Existing matching state produces 0 mutations (pure NOOP)."""
        snapshot = build_discovery_snapshot(
            services=[{"hostname": "app.example.com", "service": "http://app:8080"}],
            all_containers=[{"Names": ["/app"]}],
            docker_ok=True,
        )
        remote = self._remote_state(
            ingress_rules=[{"hostname": "app.example.com", "service": "http://app:8080"}],
            dns_records=[
                {
                    "id": "rec-1",
                    "name": "app.example.com",
                    "type": "CNAME",
                    "content": self.tunnel_target,
                    "comment": self.expected_comment,
                    "proxied": True,
                    "ttl": 1,
                }
            ],
        )

        plan = compute_change_plan(snapshot=snapshot, remote=remote, tombstones={}, now=110.0)

        self.assertFalse(plan.summary.has_mutations)
        self.assertFalse(plan.summary.is_destructive)
        self.assertTrue(all(c.action == IngressActionType.NOOP for c in plan.ingress_changes))
        self.assertTrue(all(c.action == DnsActionType.NOOP for c in plan.dns_changes))

    def test_transition_3_origin_modification_updates_ingress_only(self):
        """Lifecycle 3: Origin port/service changes -> Ingress UPDATE, DNS stays NOOP."""
        snapshot = build_discovery_snapshot(
            services=[{"hostname": "app.example.com", "service": "http://app:9000"}],  # 8080 -> 9000
            all_containers=[{"Names": ["/app"]}],
            docker_ok=True,
        )
        remote = self._remote_state(
            ingress_rules=[{"hostname": "app.example.com", "service": "http://app:8080"}],
            dns_records=[
                {
                    "id": "rec-1",
                    "name": "app.example.com",
                    "type": "CNAME",
                    "content": self.tunnel_target,
                    "comment": self.expected_comment,
                    "proxied": True,
                    "ttl": 1,
                }
            ],
        )

        plan = compute_change_plan(snapshot=snapshot, remote=remote, tombstones={}, now=120.0)

        self.assertTrue(plan.summary.has_mutations)
        self.assertFalse(plan.summary.is_destructive)
        self.assertEqual(plan.summary.ingress_updates, 1)
        self.assertEqual(plan.summary.dns_updates, 0)

    def test_transition_4_transient_stop_tombstones_without_deletion(self):
        """Lifecycle 4: Container stops -> Placed in tombstone, NOOP, zero deletions."""
        snapshot = build_discovery_snapshot(services=[], all_containers=[], docker_ok=True)
        remote = self._remote_state(
            ingress_rules=[{"hostname": "app.example.com", "service": "http://app:8080"}],
            dns_records=[
                {
                    "id": "rec-1",
                    "name": "app.example.com",
                    "type": "CNAME",
                    "content": self.tunnel_target,
                    "comment": self.expected_comment,
                }
            ],
        )

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=130.0,
            dns_delete_grace_seconds=60.0,
        )

        self.assertIn("app.example.com", plan.tombstones_to_set)
        self.assertEqual(plan.tombstones_to_set["app.example.com"], 130.0)
        self.assertFalse(plan.summary.is_destructive)
        self.assertEqual(plan.summary.ingress_deletes, 0)
        self.assertEqual(plan.summary.dns_deletes, 0)

    def test_transition_5_recovery_before_expiry_clears_tombstone(self):
        """Lifecycle 5: Container recovers before grace window -> Tombstone cleared, zero writes."""
        snapshot = build_discovery_snapshot(
            services=[{"hostname": "app.example.com", "service": "http://app:8080"}],
            all_containers=[{"Names": ["/app"]}],
            docker_ok=True,
        )
        remote = self._remote_state(
            ingress_rules=[{"hostname": "app.example.com", "service": "http://app:8080"}],
            dns_records=[
                {
                    "id": "rec-1",
                    "name": "app.example.com",
                    "type": "CNAME",
                    "content": self.tunnel_target,
                    "comment": self.expected_comment,
                    "proxied": True,
                    "ttl": 1,
                }
            ],
        )

        # 30 seconds into a 60s grace period
        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={"app.example.com": 130.0},
            now=160.0,
            dns_delete_grace_seconds=60.0,
        )

        self.assertIn("app.example.com", plan.tombstones_to_clear)
        self.assertFalse(plan.summary.has_mutations)
        self.assertFalse(plan.summary.is_destructive)

    def test_transition_6_permanent_removal_after_grace_period_expires(self):
        """Lifecycle 6: Container absent past grace window -> Ingress DELETE + DNS DELETE."""
        snapshot = build_discovery_snapshot(services=[], all_containers=[], docker_ok=True)
        remote = self._remote_state(
            ingress_rules=[{"hostname": "app.example.com", "service": "http://app:8080"}],
            dns_records=[
                {
                    "id": "rec-1",
                    "name": "app.example.com",
                    "type": "CNAME",
                    "content": self.tunnel_target,
                    "comment": self.expected_comment,
                }
            ],
        )

        # 70 seconds into a 60s grace period
        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={"app.example.com": 130.0},
            now=200.0,
            dns_delete_grace_seconds=60.0,
        )

        self.assertTrue(plan.summary.is_destructive)
        self.assertEqual(plan.summary.ingress_deletes, 1)
        self.assertEqual(plan.summary.dns_deletes, 1)
        self.assertIn("app.example.com", plan.tombstones_to_clear)

    def test_transition_7_conflict_duplicate_hostname_deterministic(self):
        """Lifecycle 7: Two containers declare identical hostname -> Deterministic first-wins."""
        snapshot = build_discovery_snapshot(
            services=[
                {"hostname": "dup.example.com", "service": "http://dup-1:80", "container_name": "dup-1"},
                {"hostname": "dup.example.com", "service": "http://dup-2:80", "container_name": "dup-2"},
            ],
            all_containers=[{"Names": ["/dup-1"]}, {"Names": ["/dup-2"]}],
            docker_ok=True,
        )
        remote = self._remote_state()

        plan1 = compute_change_plan(snapshot=snapshot, remote=remote, tombstones={}, now=300.0)
        plan2 = compute_change_plan(snapshot=snapshot, remote=remote, tombstones={}, now=300.0)

        # Deterministic identical plan output
        self.assertEqual(plan1.summary.ingress_creates, 1)
        self.assertEqual(plan1.summary.dns_creates, 1)
        self.assertEqual(plan1.final_ingress_rules, plan2.final_ingress_rules)


if __name__ == "__main__":
    unittest.main()
