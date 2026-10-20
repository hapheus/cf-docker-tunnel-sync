"""One synchronization cycle: read, plan, validate, execute, publish."""

import logging
import time
import uuid
from typing import Any, Callable, Dict

from tunnel_sync.application.executor import ChangeExecutor, DeletionPolicy
from tunnel_sync.application.inventory import InventoryResult
from tunnel_sync.application.ports import CloudflareReader, Notifications, SyncMetrics
from tunnel_sync.application.reporting import Reporter
from tunnel_sync.application.state import RuntimeState
from tunnel_sync.configuration.settings import Settings
from tunnel_sync.domain.diagnostics import compute_truthful_service_status
from tunnel_sync.domain.discovery import normalize_hostname
from tunnel_sync.domain.models import (
    BlastRadiusExceededError,
    DnsActionType,
    IngressActionType,
    OwnershipPolicy,
    RemoteState,
)
from tunnel_sync.domain.planner import compute_change_plan
from tunnel_sync.domain.snapshots import build_discovery_snapshot


class SyncService:
    def __init__(
        self,
        settings: Settings,
        runtime: RuntimeState,
        cloudflare: CloudflareReader,
        discover: Callable[[], InventoryResult | tuple[list[dict[str, Any]], list[dict[str, Any]]]],
        connector_name: Callable[[], str],
        executor: ChangeExecutor,
        reporter: Reporter,
        metrics: SyncMetrics,
        dispatcher: Notifications,
        clock: Callable[[], float] = time.time,
        new_plan_id: Callable[[], str] | None = None,
    ) -> None:
        self.settings, self.runtime, self.cloudflare = settings, runtime, cloudflare
        self.state = runtime.data
        self.discover, self.connector_name, self.executor = discover, connector_name, executor
        self.reporter, self.metrics, self.dispatcher = reporter, metrics, dispatcher
        self.clock = clock
        self.new_plan_id = new_plan_id or (lambda: f"plan-{uuid.uuid4().hex[:12]}")

    def run_once(self) -> None:
        if not self.runtime.run_lock.acquire(blocking=False):
            logging.getLogger(__name__).info("⏳ Sync already in progress, skipping concurrent run")
            return

        self.runtime.working_lock.acquire()
        sync_start_time = self.clock()
        try:
            token = self.settings.get("CLOUDFLARE_API_TOKEN")
            domain = self.settings.domain
            tunnel_name = self.settings.get("CLOUDFLARE_TUNNEL_NAME", "cf-docker-tunnel-sync").strip()
            account_id = self.settings.get("CLOUDFLARE_ACCOUNT_ID")
            if account_id:
                account_id = account_id.strip()

            self.state["status"] = "Syncing..."
            self.state["safety_guard_tripped"] = False
            self.state["safety_details"] = None
            dry_run = self.settings.get("DRY_RUN", "false").lower() in ("true", "1", "yes")
            self.state["domain_name"] = domain
            self.state["tunnel_name"] = tunnel_name

            if not token or token == "your_cloudflare_api_token_here":
                self.state["status"] = "Waiting for CLOUDFLARE_API_TOKEN in .env"
                self.reporter.add_log("⚠️ CLOUDFLARE_API_TOKEN missing or default placeholder in .env!")
                return

            if not domain or domain == "yourdomain.com":
                self.state["status"] = "Waiting for DOMAIN_NAME in .env"
                self.reporter.add_log("⚠️ DOMAIN_NAME missing or default placeholder in .env!")
                return

            # 4. Discover Docker services
            try:
                inventory = self.discover()
                if isinstance(inventory, InventoryResult):
                    services, all_containers = list(inventory.services), list(inventory.containers)
                    self.state["docker_connected"] = inventory.usable
                else:
                    services, all_containers = inventory
            except Exception as e:
                self.reporter.add_log(f"Aborting sync: Docker container discovery error: {e}")
                self.state["docker_connected"] = False
                self.state["status"] = "Docker connection degraded"
                return

            if not self.state.get("docker_connected", True):
                self.reporter.add_log("Aborting sync: Docker daemon connection is degraded or unreachable")
                self.state["status"] = "Docker connection degraded"
                return
            prev_services = list(self.state.get("discovered_services") or [])
            self.state["discovered_services"] = services
            self.state["all_containers"] = all_containers

            discovered_names = [f"{s['hostname']} ({s['service']})" for s in services]
            self.reporter.add_log(
                f"🔍 Discovered Cloudflare-labeled services: {', '.join(discovered_names) if services else 'None'}"
            )

            # 1. Resolve Zone ID (and Account ID from Zone)
            zones_resp = self.cloudflare.read(f"/zones?name={domain}", token)
            zones = zones_resp.get("result", [])
            if not zones:
                self.reporter.add_log(f"❌ Zone for domain '{domain}' not found in Cloudflare!")
                self.state["status"] = f"Error: Zone {domain} missing"
                return
            zone_id = zones[0]["id"]

            if not account_id:
                zone_account = zones[0].get("account", {})
                account_id = zone_account.get("id")

            if not account_id:
                try:
                    acc_resp = self.cloudflare.read("/accounts", token)
                    accounts = acc_resp.get("result", [])
                    if accounts:
                        account_id = accounts[0]["id"]
                except Exception:
                    pass

            if not account_id:
                self.reporter.add_log("❌ No Cloudflare accounts found for this token or zone!")
                self.state["status"] = "Error: No Account"
                return

            # 2. Tunnel
            tunnels_resp = self.cloudflare.read(
                f"/accounts/{account_id}/cfd_tunnel?name={tunnel_name}&is_deleted=false", token
            )
            tunnels = tunnels_resp.get("result", [])
            if tunnels:
                tunnel_id = tunnels[0]["id"]
            elif dry_run:
                self.state["tunnel_id"] = None
                self.reporter.add_log(
                    "[DRY-RUN] Tunnel does not exist; provisioning is required before ingress/DNS can be planned"
                )
                self.state["status"] = "Dry-Run: Tunnel provisioning required"
                self.state["last_change_plan"] = None
                self.state["_last_change_plan_obj"] = None
                self.state["_last_change_plan_api"] = None
                return
            else:
                self.reporter.add_log(f"🔨 Creating Cloudflare Tunnel '{tunnel_name}'...")
                tunnel_id = self.executor.provision(account_id, tunnel_name, token, dry_run=dry_run)

            self.state["tunnel_id"] = tunnel_id
            if not dry_run:
                token_resp = self.cloudflare.read(f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token", token)
                self.executor.activate(token_resp["result"], self.connector_name, dry_run=dry_run)

            # 5. Pure Reconciliation Pipeline (Findings A01 & F02 / Issue #46)
            target_cname = f"{tunnel_id}.cfargotunnel.com"

            # Stage 1: Build DiscoverySnapshot & RemoteState
            snapshot = build_discovery_snapshot(
                services=services,
                all_containers=all_containers,
                docker_ok=self.state.get("docker_connected", True),
                timestamp=self.clock(),
            )

            tunnel_cfg = self.cloudflare.read(f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations", token)
            existing_ingress = (
                tunnel_cfg.get("result", {}).get("config", {}).get("ingress", [])
                if isinstance(tunnel_cfg, dict) and isinstance(tunnel_cfg.get("result"), dict)
                else []
            )

            dns_records_map: Dict[str, Dict[str, Any]] = {}
            all_dns = self.cloudflare.read(f"/zones/{zone_id}/dns_records?type=CNAME&content={target_cname}", token)
            for rec in all_dns.get("result") or []:
                if isinstance(rec, dict) and rec.get("id"):
                    dns_records_map[rec["id"]] = rec

            for s in services:
                raw_h = s.get("hostname")
                norm_h = normalize_hostname(raw_h)
                if norm_h:
                    host_dns = self.cloudflare.read(f"/zones/{zone_id}/dns_records?type=CNAME&name={norm_h}", token)
                    for rec in host_dns.get("result") or []:
                        if isinstance(rec, dict) and rec.get("id"):
                            dns_records_map[rec["id"]] = rec

            remote = RemoteState(
                tunnel_id=tunnel_id,
                tunnel_name=tunnel_name,
                zone_id=zone_id,
                tunnel_target=target_cname,
                existing_ingress_rules=existing_ingress,
                existing_dns_records=list(dns_records_map.values()),
            )

            # Stage 2: Pure Reconciler Computation
            policy_str = self.settings.get("OWNERSHIP_POLICY", "adopt_and_manage").lower()
            try:
                policy = OwnershipPolicy(policy_str)
            except Exception:
                policy = OwnershipPolicy.ADOPT_AND_MANAGE

            dry_run = self.settings.get("DRY_RUN", "false").lower() in ("true", "1", "yes")
            immediate_cleanup = self.settings.get("DNS_IMMEDIATE_CLEANUP", "false").lower() in ("true", "1", "yes")
            try:
                grace_period = float(self.settings.get("DNS_CLEANUP_GRACE_PERIOD", 300.0))
            except ValueError:
                grace_period = 300.0

            # SAFE-02 Invariant: Detect sudden container drop anomalies (e.g. Docker restart/reload blip)
            if len(prev_services) >= 2 and len(services) == 0:
                self.reporter.add_log(
                    f"⚠️ [SAFETY_GUARD] Sudden container drop detected ({len(prev_services)} -> 0). "
                    f"Enforcing tombstone grace period and blocking immediate deletions."
                )
                immediate_cleanup = False
                grace_period = max(grace_period, 300.0)

            max_deletions_env = self.settings.get("MAX_DELETIONS_PER_RUN")
            max_deletions = int(max_deletions_env) if max_deletions_env and max_deletions_env.isdigit() else None

            tombstones = self.state.setdefault("tombstones", {})
            now = self.clock()

            plan = compute_change_plan(
                snapshot=snapshot,
                remote=remote,
                tombstones=tombstones,
                now=now,
                plan_id=self.new_plan_id(),
                policy=policy,
                dns_delete_grace_seconds=grace_period,
                dry_run=dry_run,
                immediate_cleanup=immediate_cleanup,
                max_deletions=max_deletions,
            )
            self.state["_last_change_plan_obj"] = plan
            self.state["last_change_plan"] = plan.model_dump()

            # Update tombstones in self.state based on planned lifecycle
            for host in plan.tombstones_to_clear:
                if host in tombstones and host in {origin.hostname for origin in snapshot.origins}:
                    del tombstones[host]
                    self.reporter.add_log(f"Container recovered for {host}, cleared tombstone")

            for host, ts in plan.tombstones_to_set.items():
                if host not in tombstones:
                    tombstones[host] = ts
                    self.reporter.add_log(f"⏳ Tombstoned {host} against flapping (grace period: {int(grace_period)}s)")

            # Log predictive diff markers
            for ing in plan.ingress_changes:
                if ing.action == IngressActionType.CREATE:
                    self.reporter.add_log(f"+ [INGRESS CREATE] {ing.hostname} -> {ing.service}")
                elif ing.action == IngressActionType.UPDATE:
                    self.reporter.add_log(f"~ [INGRESS UPDATE] {ing.hostname} -> {ing.service}")
                elif ing.action == IngressActionType.DELETE:
                    self.reporter.add_log(f"- [INGRESS DELETE] {ing.hostname}")

            for dns in plan.dns_changes:
                if dns.action == DnsActionType.CREATE:
                    self.reporter.add_log(f"+ [DNS CREATE] {dns.hostname} -> {dns.target_content}")
                elif dns.action == DnsActionType.UPDATE:
                    self.reporter.add_log(f"~ [DNS UPDATE] {dns.hostname} -> {dns.target_content}")
                elif dns.action == DnsActionType.DELETE:
                    self.reporter.add_log(f"- [DNS DELETE] {dns.hostname}")
                elif dns.action == DnsActionType.PROTECT:
                    self.reporter.add_log(f"🛡️ [DNS PROTECT] {dns.hostname} ({dns.reason})")

            # Stage 3: Execution Guardrails & Cloudflare Mutations
            if dry_run:
                self.reporter.add_log(
                    f"[DRY-RUN] ChangePlan {plan.plan_id} evaluated ({plan.summary.total_services_discovered} origins, "
                    f"{plan.summary.dns_creates} creates, {plan.summary.dns_updates} updates, "
                    f"{plan.summary.dns_deletes} deletes, {plan.summary.dns_protected} protected). "
                    "Dry-run active: skipping Cloudflare API updates."
                )
                self.reporter.record_event(
                    "info",
                    "SYNC_DRY_RUN",
                    "sync",
                    f"Dry-run plan {plan.plan_id}: {plan.summary.total_services_discovered} origins evaluated",
                )
                self.state["status"] = "Active / Synced (Dry-Run)"
                self.state["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
                return

            allow_mass_deletions = self.settings.get("ALLOW_MASS_DELETIONS", "false").lower() in ("true", "1", "yes")
            limit = self.settings.get("MAX_DELETIONS_PER_SYNC", self.settings.get("MAX_DELETIONS_PER_RUN", "3"))
            try:
                max_deletions = int(limit)
            except ValueError:
                max_deletions = 3
            ratio = self.settings.get("MAX_DELETION_RATIO")
            deletion_policy = DeletionPolicy(max_deletions, float(ratio) if ratio else None, allow_mass_deletions)
            planned_deletions = max(plan.summary.ingress_deletes, plan.summary.dns_deletes)
            current_config = tunnel_cfg.get("result", {}).get("config", {})
            execution = self.executor.execute(
                plan, token, account_id, policy=deletion_policy, current_config=current_config
            )
            ingress_failed = execution.failed("ingress")
            dns_failed = execution.failed("dns")
            if not ingress_failed:
                self.state["_last_ingress"] = plan.final_ingress_rules
            if not ingress_failed and not dns_failed:
                for host in plan.tombstones_to_clear:
                    tombstones.pop(host, None)

            # Truthful Per-Service Diagnostic Stage Updates (Issue #49)
            for s in services:
                stages = s.setdefault("stages", {})
                if ingress_failed:
                    stages["CLOUDFLARE_INGRESS"] = {
                        "status": "FAILED",
                        "message": "Cloudflare Tunnel ingress configuration update failed",
                    }
                else:
                    stages["CLOUDFLARE_INGRESS"] = {
                        "status": "PASS",
                        "message": f"Ingress rule active: {s.get('hostname')} -> {s.get('service')}",
                    }

                if dns_failed:
                    stages["CLOUDFLARE_DNS"] = {
                        "status": "FAILED",
                        "message": "Cloudflare DNS synchronization failed",
                    }
                else:
                    stages["CLOUDFLARE_DNS"] = {
                        "status": "PASS",
                        "message": f"DNS CNAME active pointing to {target_cname}",
                    }

                s["status"] = compute_truthful_service_status(stages)

            # Reconstruct synced_dns for UI & status dashboard
            synced_dns = []
            for s in services:
                norm_h = normalize_hostname(s.get("hostname"))
                if norm_h:
                    synced_dns.append(
                        {
                            "hostname": norm_h,
                            "target": target_cname,
                            "service": s.get("service", "unknown"),
                            "proxied": True,
                        }
                    )
            for rec_name, ts in list(tombstones.items()):
                remaining = max(1, int(grace_period - (now - ts)))
                self.reporter.add_log(f"⏳ DNS record for {rec_name} preserved in tombstone ({remaining}s remaining)")
                synced_dns.append(
                    {
                        "hostname": rec_name,
                        "target": target_cname,
                        "service": "tombstoned",
                        "proxied": True,
                        "tombstone_remaining": remaining,
                    }
                )

            self.state["dns_records"] = synced_dns
            self.state["services"] = services
            self.state["discovered_services"] = services

            if ingress_failed or dns_failed or any(s.get("status") in ("Degraded", "Failed") for s in services):
                self.state["status"] = "Degraded"
                self.reporter.record_event(
                    "warning",
                    "SYNC_DEGRADED",
                    "sync",
                    f"Sync completed with degraded services ({len(services)} services)",
                )
                self.reporter.add_log("⚠️ Sync completed with degraded service states.")
                if not self.settings.dry_run:
                    self.dispatcher.dispatch_sync(
                        event_type="SYNC_DEGRADED",
                        title="Sync Completed in Degraded State",
                        message="One or more services failed ingress or DNS configuration.",
                        level="warning",
                        details={"service_count": len(services)},
                    )
            else:
                self.state["status"] = "Active / Synced"
                self.reporter.record_event(
                    "info", "SYNC_SUCCESS", "sync", f"Sync completed successfully with {len(services)} services"
                )
                self.reporter.add_log("🎉 Sync completed successfully!")

            self.state["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")

            sync_duration = self.clock() - sync_start_time
            self.metrics.record_sync_run(
                duration=sync_duration,
                status="success" if self.state["status"] == "Active / Synced" else "degraded",
                discovered_count=len(services),
                safety_tripped=False,
            )

        except BlastRadiusExceededError as b_err:
            self.reporter.add_log(f"❌ {b_err}")
            self.state["status"] = "SAFETY_GUARD_TRIPPED"
            self.state["safety_guard_tripped"] = True
            self.state["safety_details"] = {
                "error": str(b_err),
                "planned_deletions": planned_deletions,
                "limit": max_deletions,
            }
            self.reporter.record_event(
                "error",
                "SAFETY_GUARD_TRIPPED",
                "sync",
                f"Blast-radius guard tripped: {planned_deletions} planned deletions exceed limit ({max_deletions})",
            )
            sync_duration = self.clock() - sync_start_time
            self.metrics.record_sync_run(
                duration=sync_duration,
                status="blocked",
                discovered_count=len(services) if "services" in locals() else 0,
                safety_tripped=True,
            )
            if not self.settings.dry_run:
                self.dispatcher.dispatch_sync(
                    event_type="SAFETY_GUARD_TRIPPED",
                    title="Blast-Radius Deletion Guard Tripped",
                    message=(
                        f"Sync cycle aborted: planned deletions ({planned_deletions}) exceed limit ({max_deletions}). "
                        "Set ALLOW_MASS_DELETIONS=true to override."
                    ),
                    level="error",
                    details={
                        "planned_deletions": planned_deletions,
                        "limit": max_deletions,
                        "error": str(b_err),
                    },
                )
        except Exception as e:
            self.reporter.add_log(f"❌ Sync Error: {e}")
            self.state["status"] = f"Error: {e}"
            self.reporter.record_event("error", "SYNC_ERROR", "sync", f"Sync error: {e}")
            sync_duration = self.clock() - sync_start_time
            self.metrics.record_sync_run(
                duration=sync_duration,
                status="error",
                discovered_count=len(services) if "services" in locals() else 0,
                safety_tripped=False,
            )
            if not self.settings.dry_run:
                self.dispatcher.dispatch_sync(
                    event_type="SYNC_FAILURE",
                    title="Synchronization Failure",
                    message=f"Sync error encountered: {e}",
                    level="error",
                    details={"error": str(e)},
                )
        finally:
            try:
                sync_duration_ms = (self.clock() - sync_start_time) * 1000.0
                services_cnt = len(services) if "services" in locals() and isinstance(services, list) else 0
                summary_info = {}
                if "plan" in locals() and hasattr(plan, "summary"):
                    summary_info = (
                        plan.summary.model_dump() if hasattr(plan.summary, "model_dump") else plan.summary.dict()
                    )
                self.reporter.record_sync_history(
                    duration_ms=sync_duration_ms,
                    status=self.state.get("status", "unknown"),
                    services_count=services_cnt,
                    summary=summary_info,
                )
                self.reporter.update_overview_metrics()
            finally:
                try:
                    self.runtime.publish()
                finally:
                    self.runtime.working_lock.release()
                    self.runtime.run_lock.release()
