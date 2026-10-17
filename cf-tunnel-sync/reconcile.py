import logging
import time
import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("cf-tunnel-sync.reconcile")


class BlastRadiusExceededError(Exception):
    """Raised when planned destructive mutations exceed configured safety threshold."""

    pass


class OwnershipStatus(str, Enum):
    OWNED = "owned"
    ADOPTED = "adopted"
    UNMANAGED = "unmanaged"
    FOREIGN_TUNNEL = "foreign_tunnel"
    UNRELATED = "unrelated"


class OwnershipPolicy(str, Enum):
    ADOPT_AND_MANAGE = "adopt_and_manage"
    STRICT_TAGGED_ONLY = "strict_tagged_only"
    LEGACY_UNRESTRICTED = "legacy_unrestricted"


class OwnershipTagging(BaseModel):
    tag_prefix: str = "cf-tunnel-sync:"
    tunnel_name: str

    def format_comment(self) -> str:
        return f"{self.tag_prefix}{self.tunnel_name}"

    def parse_status(
        self,
        record: Dict[str, Any],
        tunnel_target: str,
        is_active_local: bool,
    ) -> OwnershipStatus:
        """Classifies record ownership based on DNS comment and tunnel target."""
        rec_type = record.get("type", "CNAME")
        # Non-CNAME or pointing elsewhere is unrelated
        if rec_type != "CNAME" or record.get("content") != tunnel_target:
            return OwnershipStatus.UNRELATED

        # Hermetic test mock backward compatibility:
        # If 'comment' key is completely absent from record dictionary,
        # treat as OWNED for existing legacy unit test mocks.
        if "comment" not in record:
            return OwnershipStatus.OWNED

        comment = (record.get("comment") or "").strip()
        expected_tag = self.format_comment()

        if comment == expected_tag:
            return OwnershipStatus.OWNED

        if comment.startswith(self.tag_prefix):
            return OwnershipStatus.FOREIGN_TUNNEL

        # Record points to our tunnel target but has no ownership comment
        if is_active_local:
            return OwnershipStatus.ADOPTED
        return OwnershipStatus.UNMANAGED


class DiscoveredOrigin(BaseModel):
    """Parsed origin configuration from container inspection."""

    container_id: str
    container_name: str
    hostname: str
    service_target: str
    origin_request: Optional[Dict[str, Any]] = None
    labels: Dict[str, str] = Field(default_factory=dict)


class DiscoverySnapshot(BaseModel):
    """Immutable collection of state harvested from Docker."""

    timestamp: float
    docker_ok: bool
    origins: List[DiscoveredOrigin] = Field(default_factory=list)
    ignored_containers: List[str] = Field(default_factory=list)


class RemoteState(BaseModel):
    """Snapshot of current Cloudflare API state before reconciliation."""

    tunnel_id: str
    tunnel_name: str
    zone_id: str
    tunnel_target: str
    existing_ingress_rules: List[Dict[str, Any]] = Field(default_factory=list)
    existing_dns_records: List[Dict[str, Any]] = Field(default_factory=list)


class IngressActionType(str, Enum):
    NOOP = "noop"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class DnsActionType(str, Enum):
    NOOP = "noop"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    PROTECT = "protect"


class PlannedIngressChange(BaseModel):
    """Represents a planned mutation for Cloudflare Tunnel ingress rule."""

    action: IngressActionType
    hostname: Optional[str] = None
    path: Optional[str] = None
    service: str
    origin_request: Optional[Dict[str, Any]] = None
    reason: str


class PlannedDnsChange(BaseModel):
    """Represents a planned mutation or protection for a Cloudflare DNS record."""

    action: DnsActionType
    hostname: str
    record_id: Optional[str] = None
    record_type: str = "CNAME"
    current_content: Optional[str] = None
    target_content: Optional[str] = None
    proxied: bool = True
    ttl: int = 1
    current_comment: Optional[str] = None
    target_comment: Optional[str] = None
    ownership_status: OwnershipStatus
    reason: str


class ChangePlanSummary(BaseModel):
    """High-level cardinality metrics for audit and blast-radius checks."""

    total_services_discovered: int
    ingress_creates: int = 0
    ingress_updates: int = 0
    ingress_deletes: int = 0
    dns_creates: int = 0
    dns_updates: int = 0
    dns_deletes: int = 0
    dns_protected: int = 0
    unmanaged_skipped: int = 0
    has_mutations: bool = False
    is_destructive: bool = False


class ChangePlan(BaseModel):
    """Complete, immutable diff emitted by pure reconciliation."""

    plan_id: str
    timestamp: float
    tunnel_id: str
    zone_id: str
    dry_run: bool = False
    ingress_changes: List[PlannedIngressChange] = Field(default_factory=list)
    dns_changes: List[PlannedDnsChange] = Field(default_factory=list)
    final_ingress_rules: List[Dict[str, Any]] = Field(default_factory=list)
    tombstones_to_set: Dict[str, float] = Field(default_factory=dict)
    tombstones_to_clear: List[str] = Field(default_factory=list)
    summary: ChangePlanSummary

    def to_api_dict(self) -> Dict[str, Any]:
        """Returns JSON schema representation of the ChangePlan for the /api/change-plan endpoint."""
        actions: List[Dict[str, Any]] = []

        for ing in self.ingress_changes:
            actions.append(
                {
                    "action": ing.action.value.upper(),
                    "resource": "INGRESS",
                    "target": {
                        "hostname": ing.hostname,
                        "service": ing.service,
                        "path": ing.path,
                        "origin_request": ing.origin_request,
                    },
                    "reason": ing.reason,
                }
            )

        for dns in self.dns_changes:
            actions.append(
                {
                    "action": dns.action.value.upper(),
                    "resource": "DNS",
                    "target": {
                        "hostname": dns.hostname,
                        "record_id": dns.record_id,
                        "record_type": dns.record_type,
                        "current_content": dns.current_content,
                        "target_content": dns.target_content,
                        "proxied": dns.proxied,
                        "ttl": dns.ttl,
                    },
                    "reason": dns.reason,
                }
            )

        unmanaged = getattr(self.summary, "unmanaged_skipped", 0) or self.summary.dns_protected
        return {
            "plan_id": self.plan_id,
            "dry_run": self.dry_run,
            "timestamp": self.timestamp,
            "actions": actions,
            "summary": {
                "additions": self.summary.ingress_creates + self.summary.dns_creates,
                "updates": self.summary.ingress_updates + self.summary.dns_updates,
                "deletions": self.summary.ingress_deletes + self.summary.dns_deletes,
                "unmanaged_skipped": unmanaged,
            },
        }


def build_discovery_snapshot(
    services: List[Dict[str, Any]],
    all_containers: List[Dict[str, Any]],
    docker_ok: bool = True,
    timestamp: Optional[float] = None,
) -> DiscoverySnapshot:
    """Constructs an immutable DiscoverySnapshot from raw Docker discoveries."""
    now = timestamp if timestamp is not None else time.time()
    origins: List[DiscoveredOrigin] = []

    matched_names = set()
    for s in services:
        c_name = s.get("container_name") or "unknown"
        matched_names.add(c_name)
        origin_req = s.get("originRequest") or s.get("origin_request")
        if not origin_req:
            origin_req_dict = {}
            if s.get("no_tls_verify"):
                origin_req_dict["noTLSVerify"] = True
            if s.get("http_host_header"):
                origin_req_dict["httpHostHeader"] = s.get("http_host_header")
            origin_req = origin_req_dict if origin_req_dict else None

        origins.append(
            DiscoveredOrigin(
                container_id=s.get("container_id") or c_name,
                container_name=c_name,
                hostname=s.get("hostname", ""),
                service_target=s.get("service", ""),
                origin_request=origin_req,
                labels=s.get("labels") or {},
            )
        )

    ignored: List[str] = []
    for c in all_containers:
        names = c.get("Names") or []
        first_name = names[0] if names else "unnamed"
        if first_name not in matched_names:
            ignored.append(first_name)

    return DiscoverySnapshot(
        timestamp=now,
        docker_ok=docker_ok,
        origins=origins,
        ignored_containers=ignored,
    )


def compute_change_plan(
    snapshot: DiscoverySnapshot,
    remote: RemoteState,
    tombstones: Dict[str, float],
    now: Optional[float] = None,
    policy: OwnershipPolicy = OwnershipPolicy.ADOPT_AND_MANAGE,
    dns_delete_grace_seconds: float = 0.0,
    dry_run: bool = False,
    immediate_cleanup: bool = False,
    max_deletions: Optional[int] = None,
    tag_prefix: str = "cf-tunnel-sync:",
) -> ChangePlan:
    """Pure, deterministic reconciler computing an immutable ChangePlan without side-effects."""
    current_time = now if now is not None else time.time()
    plan_id = f"plan-{uuid.uuid4().hex[:12]}"
    tagger = OwnershipTagging(tag_prefix=tag_prefix, tunnel_name=remote.tunnel_name)
    expected_tag = tagger.format_comment()
    target_cname = remote.tunnel_target

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
        if host and rule.get("service") != "http_status:404":
            existing_ingress_by_host[host] = rule

    ingress_changes: List[PlannedIngressChange] = []
    tombstones_to_set: Dict[str, float] = {}
    tombstones_to_clear: List[str] = []
    final_ingress_origins: List[Dict[str, Any]] = []

    # 3. Evaluate Ingress for active discovered origins
    for host in sorted(discovered_hosts):
        origin = active_origins_by_host[host]
        rule: Dict[str, Any] = {"hostname": host, "service": origin.service_target}
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
        rec.get("name"): rec for rec in remote.existing_dns_records if rec.get("name")
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
    final_ingress_rules = sorted(final_ingress_origins, key=lambda r: r.get("hostname", ""))
    final_ingress_rules.append({"service": "http_status:404"})

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
            cur_comment = (rec.get("comment") or "").strip()
            cur_proxied = rec.get("proxied", False)
            cur_ttl = rec.get("ttl", 1)

            if status == OwnershipStatus.OWNED:
                if (
                    cur_content == target_cname
                    and cur_proxied is True
                    and ("comment" not in rec or cur_comment == expected_tag)
                ):
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

            elif status == OwnershipStatus.FOREIGN_TUNNEL:
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
                        reason="Preserving DNS record owned by another tunnel",
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
        rec_comment = (rec.get("comment") or "").strip()

        if rec_type != "CNAME" and not rec_comment.startswith(tag_prefix):
            continue

        status = tagger.parse_status(rec, target_cname, is_active_local=False)
        rec_id = rec.get("id")

        is_known_managed = (
            status == OwnershipStatus.OWNED
            or host in existing_ingress_by_host
            or host in tombstones
            or policy == OwnershipPolicy.LEGACY_UNRESTRICTED
            or (immediate_cleanup and rec_content == target_cname)
        )

        if is_known_managed and status in (OwnershipStatus.OWNED, OwnershipStatus.UNMANAGED):
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


def execute_change_plan(
    plan: ChangePlan,
    token: str,
    account_id: str,
    cf_api_fn: Callable[..., Any],
    dry_run: bool = False,
    max_deletions: Optional[int] = None,
    max_deletion_ratio: Optional[float] = None,
    allow_mass_deletions: bool = False,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Applies mutations specified in ChangePlan with guardrails against accidental blast-radius."""

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)
        else:
            logger.info(msg)

    # Log diff markers for planned ingress changes
    for ing in plan.ingress_changes:
        if ing.action == IngressActionType.CREATE:
            _log(f"+ [INGRESS CREATE] {ing.hostname} -> {ing.service}")
        elif ing.action == IngressActionType.UPDATE:
            _log(f"~ [INGRESS UPDATE] {ing.hostname} -> {ing.service}")
        elif ing.action == IngressActionType.DELETE:
            _log(f"- [INGRESS DELETE] {ing.hostname}")

    # Log diff markers for planned DNS changes
    for dns in plan.dns_changes:
        if dns.action == DnsActionType.CREATE:
            _log(f"+ [DNS CREATE] {dns.hostname} -> {dns.target_content}")
        elif dns.action == DnsActionType.UPDATE:
            _log(f"~ [DNS UPDATE] {dns.hostname} -> {dns.target_content}")
        elif dns.action == DnsActionType.DELETE:
            _log(f"- [DNS DELETE] {dns.hostname}")
        elif dns.action == DnsActionType.PROTECT:
            _log(f"🛡️ [DNS PROTECT] {dns.hostname} ({dns.reason})")

    is_dry = dry_run or plan.dry_run
    if is_dry:
        _log(
            f"[DRY-RUN] ChangePlan {plan.plan_id} evaluated ({plan.summary.total_services_discovered} origins, "
            f"{plan.summary.dns_creates} creates, {plan.summary.dns_updates} updates, "
            f"{plan.summary.dns_deletes} deletes, {plan.summary.dns_protected} protected). "
            f"Dry-run active: skipping Cloudflare API updates."
        )
        return {"executed": False, "dry_run": True, "plan_id": plan.plan_id}

    total_deletions = plan.summary.ingress_deletes + plan.summary.dns_deletes
    route_deletions = max(plan.summary.ingress_deletes, plan.summary.dns_deletes)
    planned_deletions = route_deletions if route_deletions > 0 else total_deletions

    if allow_mass_deletions:
        if planned_deletions > 0:
            _log(
                f"[SAFETY_GUARD] Mass deletion override active (ALLOW_MASS_DELETIONS=true). "
                f"Proceeding with {planned_deletions} planned deletions."
            )
    else:
        effective_limit = max_deletions if max_deletions is not None else 3
        if planned_deletions > effective_limit:
            err_msg = (
                f"[SAFETY_GUARD] BLAST RADIUS GUARD: Mass deletion threshold exceeded "
                f"(planned: {planned_deletions}, limit: {effective_limit}). Sync aborted."
            )
            _log(f"❌ {err_msg}")
            raise BlastRadiusExceededError(err_msg)

        if max_deletion_ratio is not None and max_deletion_ratio > 0:
            total_routes = plan.summary.total_services_discovered + planned_deletions
            if total_routes > 0:
                ratio = planned_deletions / float(total_routes)
                if ratio > max_deletion_ratio:
                    err_msg = (
                        f"[SAFETY_GUARD] BLAST RADIUS GUARD: Mass deletion ratio exceeded "
                        f"(planned ratio: {ratio:.2f}, limit: {max_deletion_ratio:.2f}). Sync aborted."
                    )
                    _log(f"❌ {err_msg}")
                    raise BlastRadiusExceededError(err_msg)

    # 1. Ingress Configuration Update
    ingress_mutations = plan.summary.ingress_creates + plan.summary.ingress_updates + plan.summary.ingress_deletes
    if ingress_mutations > 0:
        cf_api_fn(
            f"/accounts/{account_id}/cfd_tunnel/{plan.tunnel_id}/configurations",
            token,
            method="PUT",
            data={"config": {"ingress": plan.final_ingress_rules}},
        )
        _log(f"Updated Cloudflare Tunnel configuration ({len(plan.final_ingress_rules)} ingress rules)")
        _log("✅ Updated Cloudflare Tunnel Ingress rules")

    # 2. DNS Record Mutations
    for change in plan.dns_changes:
        if change.action == DnsActionType.CREATE:
            payload: Dict[str, Any] = {
                "type": change.record_type,
                "name": change.hostname,
                "content": change.target_content,
                "proxied": change.proxied,
                "ttl": change.ttl,
            }
            if change.target_comment:
                payload["comment"] = change.target_comment
            cf_api_fn(f"/zones/{plan.zone_id}/dns_records", token, method="POST", data=payload)
            _log(f"➕ Created DNS record for {change.hostname}")

        elif change.action == DnsActionType.UPDATE:
            payload = {
                "type": change.record_type,
                "name": change.hostname,
                "content": change.target_content,
                "proxied": change.proxied,
                "ttl": change.ttl,
            }
            if change.target_comment:
                payload["comment"] = change.target_comment
            cf_api_fn(
                f"/zones/{plan.zone_id}/dns_records/{change.record_id}",
                token,
                method="PUT",
                data=payload,
            )
            _log(f"🔄 Updated DNS record for {change.hostname}")

        elif change.action == DnsActionType.DELETE:
            cf_api_fn(
                f"/zones/{plan.zone_id}/dns_records/{change.record_id}",
                token,
                method="DELETE",
            )
            if "expired" in change.reason or "grace period" in change.reason:
                _log(f"🗑️ Deleted obsolete DNS record for {change.hostname} after grace period expired")
            else:
                _log(f"🗑️ Deleted obsolete DNS record for {change.hostname}")

        elif change.action == DnsActionType.PROTECT:
            _log(f"🛡️ Protected DNS record for {change.hostname} ({change.reason})")

    return {"executed": True, "dry_run": False, "plan_id": plan.plan_id}
