import os
import unittest
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

import app
from notifications import NotificationDispatcher
from reconcile import (
    ChangePlan,
    ChangePlanSummary,
    DnsActionType,
    OwnershipStatus,
    PlannedDnsChange,
    RemoteState,
    build_discovery_snapshot,
    compute_change_plan,
    execute_change_plan,
)


class TestM2PackageASafeguards(unittest.TestCase):
    """Hermetic unit tests for Milestone 2 Package A:

    - #101: SAFE-01: Strict ownership invariants
    - #102: SAFE-02: Fail-closed on Docker inventory errors & sudden drop
    - #107: SAFE-07: Deletion safeguards beyond simple count limits
    - #109: SEC-02: Credential redaction in logs, APIs, and alerts
    """

    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["logs"] = []
        app.sync_state["docker_connected"] = True
        app.sync_state["safety_guard_tripped"] = False
        app.sync_state["tombstones"] = {}
        if "_last_ingress" in app.sync_state:
            del app.sync_state["_last_ingress"]

    def test_safe_01_unmanaged_cname_never_deleted_even_with_immediate_cleanup(self):
        """SAFE-01: An unmanaged CNAME (no cf-tunnel-sync tag) pointing to the tunnel

        must NEVER be deleted, even if immediate_cleanup=True and it was present
        in existing ingress rules. It must be PROTECT.
        """
        snapshot = build_discovery_snapshot(services=[], all_containers=[], docker_ok=True)
        remote = RemoteState(
            tunnel_id="tun-123",
            tunnel_name="prod-tunnel",
            zone_id="zone-123",
            tunnel_target="tun-123.cfargotunnel.com",
            existing_ingress_rules=[
                {"hostname": "legacy.example.com", "service": "http://legacy:8080"},
                {"service": "http_status:404"},
            ],
            existing_dns_records=[
                {
                    "id": "rec-unmanaged",
                    "name": "legacy.example.com",
                    "type": "CNAME",
                    "content": "tun-123.cfargotunnel.com",
                    "comment": "",  # No ownership comment
                }
            ],
        )

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=1000.0,
            immediate_cleanup=True,
            dns_delete_grace_seconds=0.0,
        )

        # Invariant: DNS change for legacy.example.com must be PROTECT, not DELETE
        dns_deletes = [c for c in plan.dns_changes if c.action == DnsActionType.DELETE]
        self.assertEqual(len(dns_deletes), 0, "Unmanaged CNAME must never be planned for deletion")

        dns_protects = [c for c in plan.dns_changes if c.action == DnsActionType.PROTECT]
        self.assertEqual(len(dns_protects), 1)
        self.assertEqual(dns_protects[0].hostname, "legacy.example.com")
        self.assertEqual(dns_protects[0].ownership_status, OwnershipStatus.UNMANAGED)

    def test_safe_01_foreign_tunnel_record_protected_from_overwrite_and_deletion(self):
        """SAFE-01: A record owned by another tunnel must be PROTECT, never updated or deleted."""
        snapshot = build_discovery_snapshot(
            services=[{"hostname": "shared.example.com", "service": "http://svc:80"}],
            all_containers=[{"Names": ["/svc"]}],
            docker_ok=True,
        )
        remote = RemoteState(
            tunnel_id="tun-123",
            tunnel_name="tunnel-a",
            zone_id="zone-123",
            tunnel_target="tun-123.cfargotunnel.com",
            existing_ingress_rules=[{"service": "http_status:404"}],
            existing_dns_records=[
                {
                    "id": "rec-foreign",
                    "name": "shared.example.com",
                    "type": "CNAME",
                    "content": "tun-123.cfargotunnel.com",
                    "comment": "cf-tunnel-sync:tunnel-b",  # Owned by tunnel-b
                }
            ],
        )

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={},
            now=1000.0,
        )

        dns_actions = {c.hostname: c.action for c in plan.dns_changes}
        self.assertEqual(dns_actions.get("shared.example.com"), DnsActionType.PROTECT)

    def test_safe_02_docker_ok_false_plans_zero_mutations(self):
        """SAFE-02: If snapshot.docker_ok is False, compute_change_plan must return

        zero mutations (no creates, updates, or deletes).
        """
        snapshot = build_discovery_snapshot(services=[], all_containers=[], docker_ok=False)
        remote = RemoteState(
            tunnel_id="tun-123",
            tunnel_name="prod-tunnel",
            zone_id="zone-123",
            tunnel_target="tun-123.cfargotunnel.com",
            existing_ingress_rules=[
                {"hostname": "svc.example.com", "service": "http://svc:80"},
                {"service": "http_status:404"},
            ],
            existing_dns_records=[
                {
                    "id": "rec-1",
                    "name": "svc.example.com",
                    "type": "CNAME",
                    "content": "tun-123.cfargotunnel.com",
                    "comment": "cf-tunnel-sync:prod-tunnel",
                }
            ],
        )

        plan = compute_change_plan(
            snapshot=snapshot,
            remote=remote,
            tombstones={"svc.example.com": 500.0},
            now=1000.0,
            dns_delete_grace_seconds=60.0,  # Tombstone would be expired if docker was ok
        )

        self.assertFalse(plan.summary.has_mutations)
        self.assertFalse(plan.summary.is_destructive)
        self.assertEqual(plan.summary.ingress_deletes, 0)
        self.assertEqual(plan.summary.dns_deletes, 0)
        self.assertEqual(len(plan.tombstones_to_clear), 0, "Must not clear or expire tombstones when docker is not ok")

    def test_safe_02_sudden_drop_safeguard_in_app(self):
        """SAFE-02: If previous sync discovered multiple services, and current discovery

        returns 0 services, log a sudden drop warning and prevent immediate mass deletion.
        """
        app.sync_state["discovered_services"] = [
            {"hostname": "svc1.example.com", "service": "http://svc1:80"},
            {"hostname": "svc2.example.com", "service": "http://svc2:80"},
            {"hostname": "svc3.example.com", "service": "http://svc3:80"},
        ]

        with (
            patch("app.cf_api") as mock_cf,
            patch("app.docker_api") as mock_docker,
            patch.dict(
                os.environ,
                {
                    "CLOUDFLARE_API_TOKEN": "secret-token-12345678901234567890",
                    "DOMAIN_NAME": "example.com",
                    "DNS_IMMEDIATE_CLEANUP": "true",
                },
            ),
            patch("builtins.open", MagicMock()),
        ):
            mock_docker.return_value = []  # 0 containers discovered!
            cf_calls = []

            def tracked_cf(endpoint, token, method="GET", data=None):
                cf_calls.append({"endpoint": endpoint, "method": method, "data": data})
                if "/zones" in endpoint:
                    return {"result": [{"id": "z1", "account": {"id": "a1"}}]}
                if "/cfd_tunnel" in endpoint:
                    if "/token" in endpoint:
                        return {"result": "fake-token"}
                    return {"result": [{"id": "t1", "name": "cf-docker-tunnel-sync"}]}
                if "/configurations" in endpoint:
                    return {
                        "result": {
                            "config": {
                                "ingress": [
                                    {"hostname": "svc1.example.com", "service": "http://svc1:80"},
                                    {"service": "http_status:404"},
                                ]
                            }
                        }
                    }
                if "/dns_records" in endpoint:
                    return {
                        "result": [
                            {
                                "id": "rec-1",
                                "name": "svc1.example.com",
                                "type": "CNAME",
                                "content": "t1.cfargotunnel.com",
                                "comment": "cf-tunnel-sync:cf-docker-tunnel-sync",
                            }
                        ]
                    }
                return {"result": []}

            mock_cf.side_effect = tracked_cf

            app.run_sync_logic()

            # Verify sudden drop detection was logged
            drop_logs = [log for log in app.sync_state["logs"] if "Sudden container drop detected" in log]
            self.assertTrue(len(drop_logs) > 0, "Expected sudden container drop safety warning in logs")

            # Invariant: zero DELETE calls should be made under sudden drop
            deletes = [c for c in cf_calls if c["method"] == "DELETE"]
            self.assertEqual(len(deletes), 0, "Sudden drop must block immediate deletions")

    def test_safe_07_execute_change_plan_blocks_unmanaged_deletions_even_with_allow_mass(self):
        """SAFE-07: Even if allow_mass_deletions=True, unmanaged and foreign records

        must NEVER be deleted by execute_change_plan.
        """
        plan = ChangePlan(
            plan_id="plan-test",
            timestamp=1000.0,
            tunnel_id="tun-123",
            zone_id="zone-123",
            dns_changes=[
                PlannedDnsChange(
                    action=DnsActionType.PROTECT,
                    hostname="unmanaged.example.com",
                    record_id="rec-unmanaged",
                    ownership_status=OwnershipStatus.UNMANAGED,
                    reason="Safe resource ownership: unmanaged CNAME protected",
                )
            ],
            summary=ChangePlanSummary(
                total_services_discovered=0,
                dns_protected=1,
                unmanaged_skipped=1,
            ),
        )

        mock_cf_api = MagicMock()
        execute_change_plan(
            plan=plan,
            token="token-123",
            account_id="acc-123",
            cf_api_fn=mock_cf_api,
            allow_mass_deletions=True,
        )

        # No DELETE calls for protected unmanaged record
        for call_args in mock_cf_api.call_args_list:
            self.assertNotEqual(call_args.kwargs.get("method"), "DELETE")

    def test_sec_02_credential_redaction(self):
        """SEC-02: Assert tokens, tunnel secrets, and webhook credentials are redacted

        from logs, /api/status, and notification payloads.
        """
        raw_token = "Bearer ed34567890abcdef1234567890abcdef12345678"
        discord_webhook = "https://discord.com/api/webhooks/123456789/abcdefghij_secret_token"

        # 1. Logging redaction
        app.add_log(f"Received authorization header: {raw_token}")
        app.add_log(f"Alerting webhook destination: {discord_webhook}")

        latest_logs = app.sync_state["logs"][:2]
        for log_entry in latest_logs:
            self.assertNotIn("ed34567890abcdef1234567890abcdef12345678", log_entry)
            self.assertNotIn("abcdefghij_secret_token", log_entry)
            self.assertIn("[REDACTED]", log_entry)

        # 2. Status API redaction
        client = TestClient(app.app)
        resp = client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        status_text = resp.text
        self.assertNotIn("ed34567890abcdef1234567890abcdef12345678", status_text)
        self.assertNotIn("abcdefghij_secret_token", status_text)

        # 3. Webhook notification payload redaction
        dispatcher = NotificationDispatcher(webhook_url=discord_webhook)
        payload = dispatcher.format_payload(
            event_type="sync_error",
            title="Authentication Error",
            message=f"Failed with {raw_token} using {discord_webhook}",
            level="error",
            details={"token": raw_token, "url": discord_webhook},
        )

        payload_str = str(payload)
        self.assertNotIn("ed34567890abcdef1234567890abcdef12345678", payload_str)
        self.assertNotIn("abcdefghij_secret_token", payload_str)
        self.assertIn("[REDACTED]", payload_str)


if __name__ == "__main__":
    unittest.main()
