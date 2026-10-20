"""Historical reconciliation API, composed from the domain and application layers."""

import time
import uuid

from tunnel_sync.application.executor import ChangeExecutor, DeletionPolicy
from tunnel_sync.domain.models import (
    BlastRadiusExceededError as BlastRadiusExceededError,
)
from tunnel_sync.domain.models import (
    ChangePlan as DomainChangePlan,
)
from tunnel_sync.domain.models import (
    ChangePlanSummary as ChangePlanSummary,
)
from tunnel_sync.domain.models import (
    DiscoveredOrigin as DiscoveredOrigin,
)
from tunnel_sync.domain.models import (
    DiscoverySnapshot as DiscoverySnapshot,
)
from tunnel_sync.domain.models import (
    DnsActionType as DnsActionType,
)
from tunnel_sync.domain.models import (
    IngressActionType as IngressActionType,
)
from tunnel_sync.domain.models import (
    OwnershipPolicy as OwnershipPolicy,
)
from tunnel_sync.domain.models import (
    OwnershipStatus as OwnershipStatus,
)
from tunnel_sync.domain.models import (
    OwnershipTagging as OwnershipTagging,
)
from tunnel_sync.domain.models import (
    PlannedDnsChange as PlannedDnsChange,
)
from tunnel_sync.domain.models import (
    PlannedIngressChange as PlannedIngressChange,
)
from tunnel_sync.domain.models import (
    RemoteState as RemoteState,
)
from tunnel_sync.domain.planner import compute_change_plan as _plan
from tunnel_sync.domain.snapshots import build_discovery_snapshot as _snapshot
from tunnel_sync.web.serializers import serialize_change_plan


class ChangePlan(DomainChangePlan):
    """Compatibility presentation model; domain planning has no web dependency."""

    def to_api_dict(self):
        return serialize_change_plan(self)


def compute_change_plan(
    snapshot,
    remote,
    tombstones,
    now=None,
    policy=OwnershipPolicy.ADOPT_AND_MANAGE,
    dns_delete_grace_seconds=0.0,
    dry_run=False,
    immediate_cleanup=False,
    max_deletions=None,
    tag_prefix="cf-tunnel-sync:",
    *,
    plan_id=None,
):
    result = _plan(
        snapshot,
        remote,
        tombstones,
        now=time.time() if now is None else now,
        plan_id=plan_id or f"plan-{uuid.uuid4().hex[:12]}",
        policy=policy,
        dns_delete_grace_seconds=dns_delete_grace_seconds,
        dry_run=dry_run,
        immediate_cleanup=immediate_cleanup,
        max_deletions=max_deletions,
        tag_prefix=tag_prefix,
    )
    return ChangePlan(**result.model_dump())


def build_discovery_snapshot(services, all_containers, docker_ok=True, timestamp=None):
    return _snapshot(
        services, all_containers, docker_ok=docker_ok, timestamp=time.time() if timestamp is None else timestamp
    )


def execute_change_plan(
    plan,
    token,
    account_id,
    cf_api_fn,
    dry_run=False,
    max_deletions=None,
    max_deletion_ratio=None,
    allow_mass_deletions=False,
    log_fn=None,
    *,
    current_config=None,
):
    """Historical call signature delegates to the same executor with fail-fast errors."""
    from tunnel_sync.adapters.cloudflare import CloudflareWriteAdapter

    log = log_fn or (lambda message: None)
    if dry_run or plan.dry_run:
        log(f"[DRY-RUN] ChangePlan {plan.plan_id}: skipping Cloudflare API updates.")
    policy = DeletionPolicy(3 if max_deletions is None else max_deletions, max_deletion_ratio, allow_mass_deletions)
    if not (dry_run or plan.dry_run):
        try:
            policy.validate(plan)
        except BlastRadiusExceededError as error:
            log(str(error))
            raise
        ingress_mutations = plan.summary.ingress_creates + plan.summary.ingress_updates + plan.summary.ingress_deletes
        if current_config is None and ingress_mutations:
            response = cf_api_fn(
                f"/accounts/{account_id}/cfd_tunnel/{plan.tunnel_id}/configurations", token, method="GET"
            )
            current_config = response["result"]["config"]
            if not isinstance(current_config, dict):
                raise ValueError("Refusing ingress update without a valid remote configuration")
    executor = ChangeExecutor(CloudflareWriteAdapter(cf_api_fn), None, None, log)
    executor.execute(
        plan,
        token,
        account_id,
        dry_run=dry_run,
        fail_fast=True,
        policy=policy,
        current_config=current_config,
    )
    return {"executed": not (dry_run or plan.dry_run), "dry_run": dry_run or plan.dry_run, "plan_id": plan.plan_id}
