"""Pure hostname, ingress, and network plausibility transformations."""

import ipaddress
import re
import urllib.parse
from typing import List, Optional, Set

from pydantic import BaseModel

LABEL_REGEX = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_hostname(hostname: Optional[str]) -> Optional[str]:
    """Normalize and validate a hostname string according to RFC 1123.

    Strips scheme, trailing path, query/fragments, authentication, ports,
    and trailing dots. Lowercases all characters and ensures every DNS label
    satisfies RFC 1123 length and character restrictions.
    Returns None if the hostname is invalid or empty.
    """
    if not hostname or not isinstance(hostname, str):
        return None
    raw = hostname.strip()
    if not raw:
        return None
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if "?" in raw:
        raw = raw.split("?", 1)[0]
    if "#" in raw:
        raw = raw.split("#", 1)[0]
    if "@" in raw:
        raw = raw.split("@", 1)[1]
    if ":" in raw and not raw.startswith("["):
        raw = raw.split(":", 1)[0]
    raw = raw.strip().rstrip(".").lower()
    if not raw or len(raw) > 253:
        return None
    labels = raw.split(".")
    for i, label in enumerate(labels):
        if not label or len(label) > 63:
            return None
        if label == "*":
            if i != 0 or len(labels) < 2:
                return None
            continue
        if not LABEL_REGEX.match(label):
            return None
    return raw


class NetworkPlausibilityResult(BaseModel):
    is_plausible: bool
    connection_mode: str  # "shared_docker_network", "host_mode", "external_target", "gateway", "disjoint", "unknown"
    shared_networks: List[str]
    diagnostic_message: str


def evaluate_origin_network_plausibility(
    service_target: str,
    container_networks: Set[str],
    container_network_mode: Optional[str],
    connector_networks: Set[str],
) -> NetworkPlausibilityResult:
    """
    Evaluate whether origin container is plausibly reachable by Cloudflare connector container.
    Guarantees zero false-positive warnings for host network mode, loopback/gateway, and external targets.
    """
    # 1. Container in Host Network Mode
    if container_network_mode == "host" or "host" in container_networks:
        return NetworkPlausibilityResult(
            is_plausible=True,
            connection_mode="host_mode",
            shared_networks=[],
            diagnostic_message="Container operates in host network mode (direct port routing).",
        )

    # 2. Connector in Host Network Mode
    if "host" in connector_networks:
        return NetworkPlausibilityResult(
            is_plausible=True,
            connection_mode="host_mode",
            shared_networks=[],
            diagnostic_message="Connector operates in host network mode.",
        )

    # Extract target host
    target_host = ""
    if service_target:
        s = service_target.strip()
        if "://" not in s:
            s = f"http://{s}"
        try:
            parsed = urllib.parse.urlsplit(s)
            target_host = (parsed.hostname or "").lower()
        except Exception:
            target_host = ""

    # 3. Service target points to Host Loopback / Gateway
    if target_host in ("host.docker.internal", "gateway.docker.internal", "localhost", "127.0.0.1", "172.17.0.1"):
        return NetworkPlausibilityResult(
            is_plausible=True,
            connection_mode="gateway",
            shared_networks=[],
            diagnostic_message=f"Service targets host gateway or loopback interface ({target_host}).",
        )

    # 4. Service target is an external routable IP or FQDN
    if target_host:
        try:
            ip = ipaddress.ip_address(target_host)
            if not ip.is_loopback and str(ip) != "172.17.0.1":
                return NetworkPlausibilityResult(
                    is_plausible=True,
                    connection_mode="external_target",
                    shared_networks=[],
                    diagnostic_message=f"Service targets external IP address ({target_host}).",
                )
        except ValueError:
            # target_host is not an IP address (e.g. hostname/FQDN)
            pass

        if "." in target_host and not target_host.endswith(".internal") and not target_host.endswith(".local"):
            return NetworkPlausibilityResult(
                is_plausible=True,
                connection_mode="external_target",
                shared_networks=[],
                diagnostic_message=f"Service targets external FQDN ({target_host}).",
            )

    # 5. Shared Docker Network
    shared = sorted(list(container_networks.intersection(connector_networks)))
    if shared:
        return NetworkPlausibilityResult(
            is_plausible=True,
            connection_mode="shared_docker_network",
            shared_networks=shared,
            diagnostic_message=f"Container and connector share network(s): {', '.join(shared)}.",
        )

    # 6. Connector networks not discovered / empty
    if not connector_networks:
        return NetworkPlausibilityResult(
            is_plausible=True,
            connection_mode="unknown",
            shared_networks=[],
            diagnostic_message="Connector networks could not be determined; skipping strict network check.",
        )

    # 7. Disjoint Networks
    c_nets_str = ", ".join(sorted(container_networks)) if container_networks else "none"
    cf_nets_str = ", ".join(sorted(connector_networks)) if connector_networks else "none"
    return NetworkPlausibilityResult(
        is_plausible=False,
        connection_mode="disjoint",
        shared_networks=[],
        diagnostic_message=(
            f"Container networks ({c_nets_str}) do not overlap with connector networks ({cf_nets_str}). "
            f"Requests to '{service_target}' will fail with 502 Bad Gateway! Attach both containers to a shared Docker bridge network."
        ),
    )


def build_ingress_rules(services: list) -> list:
    """
    Constructs deterministic Cloudflare Tunnel ingress rules from discovered services.
    Appends the mandatory catch-all 404 rule at the end.
    """
    rules = []
    # Deterministic alphabetical sorting by hostname to prevent spurious configuration updates
    sorted_services = sorted(
        services,
        key=lambda s: normalize_hostname(s.get("hostname", "")) or s.get("hostname", ""),
    )

    for s in sorted_services:
        raw_host = s.get("hostname")
        service_target = s.get("service")
        if not raw_host or not service_target:
            continue

        hostname = normalize_hostname(raw_host)
        if not hostname:
            continue

        rule = {
            "hostname": hostname,
            "service": service_target,
        }

        origin_req = dict(s.get("originRequest", {}))
        if s.get("no_tls_verify") or s.get("noTLSVerify"):
            origin_req["noTLSVerify"] = True

        if origin_req:
            rule["originRequest"] = origin_req

        rules.append(rule)

    rules.append({"service": "http_status:404"})
    return rules
