"""Transform discovered services into planner input."""

from typing import Any, Dict, List

from tunnel_sync.domain.models import DiscoveredOrigin, DiscoverySnapshot


def build_discovery_snapshot(
    services: List[Dict[str, Any]],
    all_containers: List[Dict[str, Any]],
    timestamp: float,
    docker_ok: bool = True,
) -> DiscoverySnapshot:
    """Build planner input from discovered services; planner boundaries copy nested values."""
    now = timestamp
    origins: List[DiscoveredOrigin] = []

    matched_names = set()
    for s in services:
        c_name = s.get("container_name") or "unknown"
        matched_names.add(c_name)
        origin_req: Dict[str, Any] | None = s.get("originRequest") or s.get("origin_request")
        if not origin_req:
            origin_req_dict: Dict[str, Any] = {}
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
