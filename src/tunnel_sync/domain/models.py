"""Internal reconciliation values and ownership classification."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BlastRadiusExceededError(Exception):
    """Raised when planned destructive mutations exceed configured safety threshold."""

    def __init__(self, message: str, planned_deletions: int = 0, limit: int = 3):
        super().__init__(message)
        self.planned_deletions = planned_deletions
        self.limit = limit


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

        raw_comment = record.get("comment")
        if raw_comment is not None and not isinstance(raw_comment, str):
            return OwnershipStatus.UNMANAGED
        comment = (raw_comment or "").strip()
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
    """Point-in-time inventory; copied at application boundaries."""

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
    """Diff emitted by reconciliation; copied at application boundaries."""

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
