"""Deterministic reconciliation: no I/O, environment, clock, or random IDs."""

from copy import deepcopy
from typing import Any, Dict, List, Optional

from tunnel_sync.domain.ingress import merge_ingress
from tunnel_sync.domain.models import (
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
)


def compute_change_plan(
    snapshot: DiscoverySnapshot,
    remote: RemoteState,
    tombstones: Dict[str, float],
    now: float,
    plan_id: str,
    policy: OwnershipPolicy = OwnershipPolicy.ADOPT_AND_MANAGE,
    dns_delete_grace_seconds: float = 0.0,
    dry_run: bool = False,
    immediate_cleanup: bool = False,
    max_deletions: Optional[int] = None,
    tag_prefix: str = "cf-tunnel-sync:",
) -> ChangePlan:
    """Compute a plan from explicit snapshots, policies, time, and identity."""
    snapshot = snapshot.model_copy(deep=True)
    remote = remote.model_copy(deep=True)
    current_time = now
    tagger = OwnershipTagging(tag_prefix=tag_prefix, tunnel_name=remote.tunnel_name)
    expected_tag = tagger.format_comment()
    target_cname = remote.tunnel_target

    # SAFE-02 Invariant: Fail-closed on Docker inventory error/degradation
    if not snapshot.docker_ok:
        return _degraded_plan(remote, current_time, plan_id, dry_run, tagger)

    # 1. Map active discovered origins by normalized hostname
    active_origins_by_host: Dict[str, DiscoveredOrigin] = {}
    for o in snapshot.origins:
        if o.hostname:
            active_origins_by_host[o.hostname] = o
    discovered_hosts = set(active_origins_by_host.keys())

    # 2. Map existing ingress rules by hostname (excluding 404 catch-all)
    existing_ingress_by_host: Dict[str, Dict[str, Any]] = {}
    for rule in remote.existing_ingress_rules:
        host = rule.get("hostname")
        if host and not rule.get("path"):
            existing_ingress_by_host.setdefault(host, rule)

    ingress_changes: List[PlannedIngressChange] = []
    tombstones_to_set: Dict[str, float] = {}
    tombstones_to_clear: List[str] = []
    final_ingress_origins: List[Dict[str, Any]] = []

    # 3. Evaluate Ingress for active discovered origins
    for host in sorted(discovered_hosts):
        origin = active_origins_by_host[host]
        rule = {"hostname": host, "service": origin.service_target}
        if origin.origin_request:
            rule["originRequest"] = origin.origin_request

        if host in existing_ingress_by_host:
            existing_rule = existing_ingress_by_host[host]
            existing_svc = existing_rule.get("service")
            existing_req = existing_rule.get("originRequest") or {}
            target_req = rule.get("originRequest") or {}

            if existing_svc == rule["service"] and existing_req == target_req:
                ingress_changes.append(
                    PlannedIngressChange(
                        action=IngressActionType.NOOP,
                        hostname=host,
                        service=rule["service"],
                        origin_request=rule.get("originRequest"),
                        reason="Ingress rule matches remote configuration",
                    )
                )
            else:
                ingress_changes.append(
                    PlannedIngressChange(
                        action=IngressActionType.UPDATE,
                        hostname=host,
                        service=rule["service"],
                        origin_request=rule.get("originRequest"),
                        reason=f"Origin service/request modified: {existing_svc} -> {rule['service']}",
                    )
                )
        else:
            ingress_changes.append(
                PlannedIngressChange(
                    action=IngressActionType.CREATE,
                    hostname=host,
                    service=rule["service"],
                    origin_request=rule.get("originRequest"),
                    reason="New container discovered",
                )
            )

        final_ingress_origins.append(rule)

        if host in tombstones:
            tombstones_to_clear.append(host)

    # Build DNS index for evaluation
    existing_dns_by_name: Dict[str, Dict[str, Any]] = {
        str(rec["name"]): rec for rec in remote.existing_dns_records if rec.get("name")
    }

    # 4. Evaluate Ingress for missing origins (previously configured)
    for host, rule in existing_ingress_by_host.items():
        if host not in discovered_hosts:
            dns_rec = existing_dns_by_name.get(host)
            dns_status = tagger.parse_status(dns_rec, target_cname, is_active_local=False) if dns_rec else None
            # Preserve unmanaged / manual external ingress rules across upgrade (Issue #86)
            if dns_rec is None or dns_status != OwnershipStatus.OWNED:
                final_ingress_origins.append(rule)
                ingress_changes.append(
                    PlannedIngressChange(
                        action=IngressActionType.NOOP,
                        hostname=host,
                        service=rule.get("service", ""),
                        path=rule.get("path"),
                        origin_request=rule.get("originRequest"),
                        reason="Unmanaged external ingress rule preserved across upgrade",
                    )
                )
                continue
            if immediate_cleanup or dns_delete_grace_seconds <= 0:
                ingress_changes.append(
                    PlannedIngressChange(
                        action=IngressActionType.DELETE,
                        hostname=host,
                        service=rule.get("service", ""),
                        reason="Discovered container removed and immediate cleanup active",
                    )
                )
                if host in tombstones:
                    tombstones_to_clear.append(host)
            else:
                if host not in tombstones:
                    tombstones_to_set[host] = current_time
                    final_ingress_origins.append(rule)
                    ingress_changes.append(
                        PlannedIngressChange(
                            action=IngressActionType.NOOP,
                            hostname=host,
                            service=rule.get("service", ""),
                            reason=f"Tombstoned {host} for {int(dns_delete_grace_seconds)}s (waiting for container to recover)",
                        )
                    )
                else:
                    elapsed = current_time - tombstones[host]
                    if elapsed >= dns_delete_grace_seconds:
                        ingress_changes.append(
                            PlannedIngressChange(
                                action=IngressActionType.DELETE,
                                hostname=host,
                                service=rule.get("service", ""),
                                reason=f"Tombstone expired for {host} after {int(dns_delete_grace_seconds)}s, cleaning up ingress",
                            )
                        )
                        tombstones_to_clear.append(host)
                    else:
                        remaining = max(1, int(dns_delete_grace_seconds - elapsed))
                        final_ingress_origins.append(rule)
                        ingress_changes.append(
                            PlannedIngressChange(
                                action=IngressActionType.NOOP,
                                hostname=host,
                                service=rule.get("service", ""),
                                reason=f"Preserved in tombstone ({remaining}s remaining)",
                            )
                        )

    # Ingress Catch-All Invariant
    final_ingress_rules = merge_ingress(remote.existing_ingress_rules, final_ingress_origins)

    # 5. Evaluate DNS Records
    dns_changes: List[PlannedDnsChange] = []
    existing_dns_by_host: Dict[str, Dict[str, Any]] = {}
    for r in remote.existing_dns_records:
        r_name = r.get("name")
        if r_name:
            existing_dns_by_host[r_name] = r

    # 5.1 Active Discovered Hostnames
    for host in sorted(discovered_hosts):
        rec = existing_dns_by_host.get(host)
        if rec is None:
            dns_changes.append(
                PlannedDnsChange(
                    action=DnsActionType.CREATE,
                    hostname=host,
                    record_id=None,
                    record_type="CNAME",
                    current_content=None,
                    target_content=target_cname,
                    proxied=True,
                    ttl=1,
                    current_comment=None,
                    target_comment=expected_tag,
                    ownership_status=OwnershipStatus.OWNED,
                    reason="Create new DNS CNAME record",
                )
            )
        else:
            status = tagger.parse_status(rec, target_cname, is_active_local=True)
            rec_id = rec.get("id")
            cur_content = rec.get("content")
            cur_comment = _comment_text(rec.get("comment"))
            cur_proxied = rec.get("proxied", False)
            cur_ttl = rec.get("ttl", 1)

            if status == OwnershipStatus.OWNED:
                if cur_content == target_cname and cur_proxied is True and cur_comment == expected_tag:
                    dns_changes.append(
                        PlannedDnsChange(
                            action=DnsActionType.NOOP,
                            hostname=host,
                            record_id=rec_id,
                            current_content=cur_content,
                            target_content=target_cname,
                            proxied=True,
                            ttl=1,
                            current_comment=cur_comment,
                            target_comment=expected_tag,
                            ownership_status=status,
                            reason="Record matches tunnel target and ownership tag",
                        )
                    )
                else:
                    dns_changes.append(
                        PlannedDnsChange(
                            action=DnsActionType.UPDATE,
                            hostname=host,
                            record_id=rec_id,
                            current_content=cur_content,
                            target_content=target_cname,
                            proxied=True,
                            ttl=1,
                            current_comment=cur_comment,
                            target_comment=expected_tag,
                            ownership_status=status,
                            reason="Updating existing owned record configuration",
                        )
                    )

            elif status == OwnershipStatus.ADOPTED:
                if policy == OwnershipPolicy.STRICT_TAGGED_ONLY:
                    dns_changes.append(
                        PlannedDnsChange(
                            action=DnsActionType.PROTECT,
                            hostname=host,
                            record_id=rec_id,
                            current_content=cur_content,
                            target_content=target_cname,
                            proxied=cur_proxied,
                            ttl=cur_ttl,
                            current_comment=cur_comment,
                            target_comment=None,
                            ownership_status=status,
                            reason="Strict tagged-only policy: unmanaged record protected from adoption",
                        )
                    )
                else:
                    dns_changes.append(
                        PlannedDnsChange(
                            action=DnsActionType.UPDATE,
                            hostname=host,
                            record_id=rec_id,
                            current_content=cur_content,
                            target_content=target_cname,
                            proxied=True,
                            ttl=1,
                            current_comment=cur_comment,
                            target_comment=expected_tag,
                            ownership_status=status,
                            reason="Adopting unmanaged DNS record pointing to tunnel",
                        )
                    )

            elif status in (OwnershipStatus.FOREIGN_TUNNEL, OwnershipStatus.UNMANAGED):
                dns_changes.append(
                    PlannedDnsChange(
                        action=DnsActionType.PROTECT,
                        hostname=host,
                        record_id=rec_id,
                        current_content=cur_content,
                        target_content=target_cname,
                        proxied=cur_proxied,
                        ttl=cur_ttl,
                        current_comment=cur_comment,
                        target_comment=None,
                        ownership_status=status,
                        reason="Preserving DNS record without matching ownership metadata",
                    )
                )

            elif status == OwnershipStatus.UNRELATED:
                dns_changes.append(
                    PlannedDnsChange(
                        action=DnsActionType.PROTECT,
                        hostname=host,
                        record_id=rec_id,
                        current_content=cur_content,
                        target_content=target_cname,
                        proxied=cur_proxied,
                        ttl=cur_ttl,
                        current_comment=cur_comment,
                        target_comment=None,
                        ownership_status=status,
                        reason="Preserving manual or unrelated DNS record pointing to different destination",
                    )
                )

    # 5.2 Missing Hostnames in Remote DNS
    for rec in remote.existing_dns_records:
        host = rec.get("name")
        if not host or host in discovered_hosts:
            continue

        # Filter relevant records
        rec_type = rec.get("type", "CNAME")
        rec_content = rec.get("content")
        rec_comment = _comment_text(rec.get("comment"))

        if rec_type != "CNAME" and not rec_comment.startswith(tag_prefix):
            continue

        status = tagger.parse_status(rec, target_cname, is_active_local=False)
        rec_id = rec.get("id")

        # SAFE-01 Invariant: Only records explicitly verified as OWNED (matching tunnel comment tag
        # and tunnel target) can ever be planned for automated deletion. Unmanaged, foreign, or
        # unrelated records must strictly be protected and never deleted.
        is_known_managed = status == OwnershipStatus.OWNED or (
            policy == OwnershipPolicy.LEGACY_UNRESTRICTED
            and (
                host in existing_ingress_by_host
                or host in tombstones
                or (immediate_cleanup and rec_content == target_cname)
            )
        )

        if is_known_managed and (status == OwnershipStatus.OWNED or policy == OwnershipPolicy.LEGACY_UNRESTRICTED):
            if immediate_cleanup or dns_delete_grace_seconds <= 0:
                dns_changes.append(
                    PlannedDnsChange(
                        action=DnsActionType.DELETE,
                        hostname=host,
                        record_id=rec_id,
                        current_content=rec_content,
                        target_content=None,
                        proxied=rec.get("proxied", True),
                        ttl=rec.get("ttl", 1),
                        current_comment=rec_comment,
                        target_comment=None,
                        ownership_status=status,
                        reason="Discovered container removed and grace period expired",
                    )
                )
                if host in tombstones:
                    tombstones_to_clear.append(host)
            else:
                if host not in tombstones:
                    tombstones_to_set[host] = current_time
                    dns_changes.append(
                        PlannedDnsChange(
                            action=DnsActionType.NOOP,
                            hostname=host,
                            record_id=rec_id,
                            current_content=rec_content,
                            target_content=rec_content,
                            proxied=rec.get("proxied", True),
                            ttl=rec.get("ttl", 1),
                            current_comment=rec_comment,
                            target_comment=rec_comment,
                            ownership_status=status,
                            reason=f"Tombstoned {host} for {int(dns_delete_grace_seconds)}s (waiting for container to recover)",
                        )
                    )
                else:
                    elapsed = current_time - tombstones[host]
                    if elapsed >= dns_delete_grace_seconds:
                        dns_changes.append(
                            PlannedDnsChange(
                                action=DnsActionType.DELETE,
                                hostname=host,
                                record_id=rec_id,
                                current_content=rec_content,
                                target_content=None,
                                proxied=rec.get("proxied", True),
                                ttl=rec.get("ttl", 1),
                                current_comment=rec_comment,
                                target_comment=None,
                                ownership_status=status,
                                reason=f"Tombstone expired for {host} after {int(dns_delete_grace_seconds)}s, cleaning up DNS",
                            )
                        )
                        tombstones_to_clear.append(host)
                    else:
                        remaining = max(1, int(dns_delete_grace_seconds - elapsed))
                        dns_changes.append(
                            PlannedDnsChange(
                                action=DnsActionType.NOOP,
                                hostname=host,
                                record_id=rec_id,
                                current_content=rec_content,
                                target_content=rec_content,
                                proxied=rec.get("proxied", True),
                                ttl=rec.get("ttl", 1),
                                current_comment=rec_comment,
                                target_comment=rec_comment,
                                ownership_status=status,
                                reason=f"Preserved in tombstone ({remaining}s remaining)",
                            )
                        )

        elif status == OwnershipStatus.UNMANAGED:
            dns_changes.append(
                PlannedDnsChange(
                    action=DnsActionType.PROTECT,
                    hostname=host,
                    record_id=rec_id,
                    current_content=rec_content,
                    target_content=None,
                    proxied=rec.get("proxied", True),
                    ttl=rec.get("ttl", 1),
                    current_comment=rec_comment,
                    target_comment=None,
                    ownership_status=status,
                    reason="Safe resource ownership: unmanaged CNAME protected from automated deletion",
                )
            )

        elif status == OwnershipStatus.FOREIGN_TUNNEL:
            dns_changes.append(
                PlannedDnsChange(
                    action=DnsActionType.PROTECT,
                    hostname=host,
                    record_id=rec_id,
                    current_content=rec_content,
                    target_content=None,
                    proxied=rec.get("proxied", True),
                    ttl=rec.get("ttl", 1),
                    current_comment=rec_comment,
                    target_comment=None,
                    ownership_status=status,
                    reason="Safe resource ownership: foreign tunnel CNAME protected from deletion",
                )
            )

        elif status == OwnershipStatus.UNRELATED:
            dns_changes.append(
                PlannedDnsChange(
                    action=DnsActionType.PROTECT,
                    hostname=host,
                    record_id=rec_id,
                    current_content=rec_content,
                    target_content=None,
                    proxied=rec.get("proxied", True),
                    ttl=rec.get("ttl", 1),
                    current_comment=rec_comment,
                    target_comment=None,
                    ownership_status=status,
                    reason="Safe resource ownership: unrelated record protected",
                )
            )

    # 6. Compute Cardinality Summary
    ing_creates = sum(1 for c in ingress_changes if c.action == IngressActionType.CREATE)
    ing_updates = sum(1 for c in ingress_changes if c.action == IngressActionType.UPDATE)
    ing_deletes = sum(1 for c in ingress_changes if c.action == IngressActionType.DELETE)

    dns_creates = sum(1 for c in dns_changes if c.action == DnsActionType.CREATE)
    dns_updates = sum(1 for c in dns_changes if c.action == DnsActionType.UPDATE)
    dns_deletes = sum(1 for c in dns_changes if c.action == DnsActionType.DELETE)
    dns_protected = sum(1 for c in dns_changes if c.action == DnsActionType.PROTECT)

    has_mutations = (ing_creates + ing_updates + ing_deletes + dns_creates + dns_updates + dns_deletes) > 0
    is_destructive = (ing_deletes + dns_deletes) > 0

    unmanaged_skipped = sum(
        1
        for c in dns_changes
        if c.action == DnsActionType.PROTECT
        or c.ownership_status in (OwnershipStatus.UNMANAGED, OwnershipStatus.FOREIGN_TUNNEL)
    )

    summary = ChangePlanSummary(
        total_services_discovered=len(snapshot.origins),
        ingress_creates=ing_creates,
        ingress_updates=ing_updates,
        ingress_deletes=ing_deletes,
        dns_creates=dns_creates,
        dns_updates=dns_updates,
        dns_deletes=dns_deletes,
        dns_protected=dns_protected,
        unmanaged_skipped=unmanaged_skipped,
        has_mutations=has_mutations,
        is_destructive=is_destructive,
    )

    return ChangePlan(
        plan_id=plan_id,
        timestamp=current_time,
        tunnel_id=remote.tunnel_id,
        zone_id=remote.zone_id,
        dry_run=dry_run,
        ingress_changes=ingress_changes,
        dns_changes=dns_changes,
        final_ingress_rules=final_ingress_rules,
        tombstones_to_set=tombstones_to_set,
        tombstones_to_clear=sorted(list(set(tombstones_to_clear))),
        summary=summary,
    )


def _degraded_plan(
    remote: RemoteState, current_time: float, plan_id: str, dry_run: bool, tagger: OwnershipTagging
) -> ChangePlan:
    ingress_changes: List[PlannedIngressChange] = []
    final_ingress_origins: List[Dict[str, Any]] = []
    for rule in remote.existing_ingress_rules:
        if rule.get("service") != "http_status:404":
            final_ingress_origins.append(rule)
            ingress_changes.append(
                PlannedIngressChange(
                    action=IngressActionType.NOOP,
                    hostname=rule.get("hostname"),
                    service=rule.get("service", ""),
                    origin_request=rule.get("originRequest"),
                    reason="Docker discovery degraded: preserving existing ingress rule (fail-closed)",
                )
            )

    final_ingress_rules = deepcopy(remote.existing_ingress_rules)

    dns_changes: List[PlannedDnsChange] = []
    for rec in remote.existing_dns_records:
        h = rec.get("name")
        if not h:
            continue
        rec_status = tagger.parse_status(rec, remote.tunnel_target, is_active_local=False)
        dns_changes.append(
            PlannedDnsChange(
                action=DnsActionType.PROTECT,
                hostname=h,
                record_id=rec.get("id"),
                current_content=rec.get("content"),
                target_content=rec.get("content"),
                proxied=rec.get("proxied", True),
                ttl=rec.get("ttl", 1),
                current_comment=rec.get("comment"),
                target_comment=rec.get("comment"),
                ownership_status=rec_status,
                reason="Docker discovery degraded: preserving DNS record (fail-closed)",
            )
        )

    summary = ChangePlanSummary(
        total_services_discovered=0,
        ingress_creates=0,
        ingress_updates=0,
        ingress_deletes=0,
        dns_creates=0,
        dns_updates=0,
        dns_deletes=0,
        dns_protected=len(dns_changes),
        unmanaged_skipped=len(dns_changes),
        has_mutations=False,
        is_destructive=False,
    )

    return ChangePlan(
        plan_id=plan_id,
        timestamp=current_time,
        tunnel_id=remote.tunnel_id,
        zone_id=remote.zone_id,
        dry_run=dry_run,
        ingress_changes=ingress_changes,
        dns_changes=dns_changes,
        final_ingress_rules=final_ingress_rules,
        tombstones_to_set={},
        tombstones_to_clear=[],
        summary=summary,
    )


def _comment_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
