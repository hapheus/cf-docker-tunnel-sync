"""Predictive local inspection with an inventory reader and no write capability."""

import time
import uuid
from typing import Any, Callable

from tunnel_sync.domain.models import RemoteState
from tunnel_sync.domain.planner import compute_change_plan
from tunnel_sync.domain.snapshots import build_discovery_snapshot


def compute_preview(
    settings,
    state: dict[str, Any],
    discover: Callable,
    *,
    zone_id: str,
    existing_ingress: list[dict] | None = None,
    clock=time.time,
    new_plan_id=None,
):
    services, containers = discover()
    now = clock()
    snapshot = build_discovery_snapshot(
        services, containers, timestamp=now, docker_ok=state.get("docker_connected", True)
    )
    tunnel_id = state.get("tunnel_id") or "preview-tunnel-id"
    remote = RemoteState(
        tunnel_id=tunnel_id,
        tunnel_name=settings.get("CLOUDFLARE_TUNNEL_NAME", "cf-docker-tunnel-sync").strip(),
        zone_id=zone_id,
        tunnel_target=f"{tunnel_id}.cfargotunnel.com",
        existing_ingress_rules=existing_ingress or [],
    )
    return compute_change_plan(
        snapshot,
        remote,
        state.get("tombstones", {}),
        now=now,
        plan_id=(new_plan_id or (lambda: f"plan-{uuid.uuid4().hex[:12]}"))(),
        dry_run=True,
    )
