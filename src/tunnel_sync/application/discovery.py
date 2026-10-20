"""Inventory discovery and Docker-label interpretation."""

import logging
import socket
import threading
from copy import deepcopy
from typing import Any, Dict, List, Optional

from tunnel_sync.application.inventory import InventoryResult, InventoryStatus, InventoryUnavailableError
from tunnel_sync.domain.diagnostics import compute_truthful_service_status, evaluate_service_stages
from tunnel_sync.domain.discovery import (
    NetworkPlausibilityResult,
    evaluate_origin_network_plausibility,
    normalize_hostname,
)
from tunnel_sync.domain.labels import LEGACY_LABEL_CANONICAL_MAP, first_label, parse_origin_labels

logger = logging.getLogger(__name__)


class DiscoveryService:
    def __init__(self, settings, docker, state, log, lock=None):
        self.settings, self.docker, self.state, self.log = settings, docker, state, log
        self.lock = lock if lock is not None else threading.RLock()
        self.inventory_status = InventoryStatus.AVAILABLE
        self.inventory_reason = ""

    def collect(self) -> InventoryResult:
        with self.lock:
            # Availability belongs to this read, never to the previous cycle's list.
            self.state["docker_connected"] = True
            services, containers = self._discover()
            return InventoryResult(
                self.inventory_status, tuple(deepcopy(services)), tuple(deepcopy(containers)), self.inventory_reason
            )

    def discover(self) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Compatibility tuple; workflows should consume collect() availability."""
        with self.lock:
            return self._discover()

    def resolve_target_connector_container(self, containers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Resolve the single target cloudflared connector container among running containers.
        Prevents network bleeding across unrelated cloudflared instances or compose projects.
        """
        if not isinstance(containers, list):
            return None

        explicit_name = self.settings.get("CLOUDFLARED_CONTAINER_NAME", "").strip()

        # 1. If explicit CLOUDFLARED_CONTAINER_NAME is configured, match strictly against that container
        if explicit_name:
            for c in containers:
                if not isinstance(c, dict):
                    continue
                c_id = c.get("Id", "")
                c_names = [n.lstrip("/") for n in c.get("Names", [])]
                c_labels = c.get("Labels") or {}
                if (
                    explicit_name in c_names
                    or c_id == explicit_name
                    or (len(explicit_name) >= 12 and c_id.startswith(explicit_name))
                    or c_labels.get("com.docker.compose.service") == explicit_name
                ):
                    return c
            return None

        # 2. Scope to current Compose project if detectable
        my_hostname = self.settings.get("HOSTNAME") or socket.gethostname()
        current_project = None
        for c in containers:
            if not isinstance(c, dict):
                continue
            c_id = c.get("Id", "")
            c_names = [n.lstrip("/") for n in c.get("Names", [])]
            c_labels = c.get("Labels") or {}
            if (
                c_id.startswith(my_hostname)
                or my_hostname in c_names
                or c_labels.get("com.docker.compose.service") in ("cf-docker-tunnel-sync", "tunnel-sync")
            ):
                current_project = c_labels.get("com.docker.compose.project")
                if current_project:
                    break

        if current_project:
            for c in containers:
                if not isinstance(c, dict):
                    continue
                c_labels = c.get("Labels") or {}
                if c_labels.get("com.docker.compose.project") == current_project:
                    c_names = [n.lstrip("/") for n in c.get("Names", [])]
                    if c_labels.get("com.docker.compose.service") == "cloudflared" or "cloudflared" in c_names:
                        return c

        # 3. Match exact container name 'cloudflared'
        for c in containers:
            if not isinstance(c, dict):
                continue
            c_names = [n.lstrip("/") for n in c.get("Names", [])]
            if "cloudflared" in c_names:
                return c

        # 4. If unambiguous single container with compose service 'cloudflared' exists, match it
        cf_service_matches = [
            c
            for c in containers
            if isinstance(c, dict) and (c.get("Labels") or {}).get("com.docker.compose.service") == "cloudflared"
        ]
        if len(cf_service_matches) == 1:
            return cf_service_matches[0]

        return None

    def find_cloudflared_container_name(self, containers: Optional[List[Dict[str, Any]]] = None) -> str:
        """Resolve the cloudflared container name or ID dynamically."""
        explicit_name = self.settings.get("CLOUDFLARED_CONTAINER_NAME", "").strip()
        if explicit_name:
            return explicit_name

        if containers is not None:
            target = self.resolve_target_connector_container(containers)
            if target:
                c_names = [n.lstrip("/") for n in target.get("Names", [])]
                if c_names:
                    return c_names[0]
                return target.get("Id", "cloudflared")
            return "cloudflared"

        try:
            raw_containers = self.docker.request("/containers/json?all=true")
            if isinstance(raw_containers, list):
                target = self.resolve_target_connector_container(raw_containers)
                if target:
                    c_names = [n.lstrip("/") for n in target.get("Names", [])]
                    if c_names:
                        return c_names[0]
                    return target.get("Id", "cloudflared")
        except Exception as e:
            logger.warning(f"Error resolving cloudflared container: {e}")

        return "cloudflared"

    def _discover(self) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        self.inventory_status = InventoryStatus.AVAILABLE
        self.inventory_reason = ""
        services = []
        all_containers = []
        seen_hostnames = set()
        configured_domain = self.settings.domain.lower()
        configured_tunnel_name = self.settings.get("CLOUDFLARE_TUNNEL_NAME", "cf-docker-tunnel-sync").strip()

        try:
            expected_network = self.settings.get("CF_NETWORK_NAME", "cf-tunnel-net").strip()
            require_shared_net = self.settings.get("REQUIRE_SHARED_NETWORK", "false").lower() in ("true", "1", "yes")
            strict_network_check = self.settings.get("STRICT_NETWORK_CHECK", "false").lower() in ("true", "1", "yes")
            enforce_strict_network = strict_network_check or require_shared_net

            cloudflared_networks = set()
            if expected_network:
                cloudflared_networks.add(expected_network)

            containers = self.docker.request("/containers/json?all=true")
            if not isinstance(containers, list):
                self.inventory_status = InventoryStatus.DEGRADED
                self.inventory_reason = "Docker container discovery returned non-list response"
                self.state["docker_connected"] = False
                self.log("Docker API container discovery returned non-list response; failing closed")
                return [], []

            if containers:
                self.state["docker_connected"] = True
            elif not self.state.get("docker_connected", True):
                self.inventory_status = InventoryStatus.UNAVAILABLE
                self.inventory_reason = "Docker connection is unavailable"
                return [], []

            if isinstance(containers, list):
                target_connector = self.resolve_target_connector_container(containers)
                if target_connector:
                    target_nets = (target_connector.get("NetworkSettings") or {}).get("Networks") or {}
                    cloudflared_networks.update(target_nets.keys())
                    target_net_mode = (target_connector.get("HostConfig") or {}).get("NetworkMode")
                    if target_net_mode == "host":
                        cloudflared_networks.add("host")

                for c in containers:
                    # Cleanly reset per-container evaluation flags
                    is_tunneled = False
                    has_shared_net = True
                    service_url = ""
                    plausibility: Optional[NetworkPlausibilityResult] = None

                    labels = c.get("Labels") or {}
                    c_names = c.get("Names", ["/unknown"])
                    c_name = c_names[0].lstrip("/") if c_names else "unknown"
                    for leg_key, canonical in LEGACY_LABEL_CANONICAL_MAP.items():
                        if leg_key in labels:
                            warn_key = (c_name, leg_key)
                            if warn_key not in self.state.setdefault("_deprecations_warned", set()):
                                self.state["_deprecations_warned"].add(warn_key)
                                self.log(
                                    f"⚠️ Deprecation Notice: Container '{c_name}' uses legacy alias '{leg_key}'. Please migrate to canonical '{canonical}'."
                                )
                    state = c.get("State", "unknown")
                    status_text = c.get("Status", "")
                    image = c.get("Image", "")

                    raw_hostname = first_label(labels, "cf.tunnel.hostname")

                    hostname = ""
                    if raw_hostname:
                        normalized = normalize_hostname(str(raw_hostname))
                        if not normalized:
                            self.log(
                                f"⚠️ Invalid hostname '{raw_hostname}' for container '{c_name}' rejected (must be valid RFC 1123)"
                            )
                        else:
                            hostname = normalized

                    # Domain scoping: only match if hostname belongs to configured DOMAIN_NAME
                    matches_domain = True
                    if configured_domain and hostname:
                        matches_domain = (hostname == configured_domain) or (hostname.endswith("." + configured_domain))

                    # Optional tunnel scoping: if cf.tunnel.name is set, verify it matches CLOUDFLARE_TUNNEL_NAME
                    target_tunnel = first_label(labels, "cf.tunnel.name")
                    matches_tunnel = True
                    if target_tunnel:
                        matches_tunnel = str(target_tunnel).strip() == configured_tunnel_name

                    is_tunneled = False
                    service_url = ""

                    if hostname and state == "running" and matches_domain and matches_tunnel:
                        if hostname in seen_hostnames:
                            self.log(f"⚠️ Duplicate hostname '{hostname}' for container '{c_name}' ignored")
                        else:
                            seen_hostnames.add(hostname)
                            is_tunneled = True

                            parsed = parse_origin_labels(labels, c_name, c.get("Ports", []))
                            service_url = parsed.service_target
                            origin_request = parsed.origin_request
                            no_tls_verify = parsed.no_tls_verify
                            for warning in parsed.warnings:
                                self.log(warning)

                            # Origin Network Pre-flight Diagnostic
                            c_nets = (c.get("NetworkSettings") or {}).get("Networks") or {}
                            container_networks = set(c_nets.keys())
                            container_network_mode = (c.get("HostConfig") or {}).get("NetworkMode")

                            plausibility = evaluate_origin_network_plausibility(
                                service_target=service_url,
                                container_networks=container_networks,
                                container_network_mode=container_network_mode,
                                connector_networks=cloudflared_networks,
                            )
                            has_shared_net = plausibility.is_plausible

                            if not has_shared_net:
                                target_net_display = expected_network or (
                                    ", ".join(sorted(cloudflared_networks))
                                    if cloudflared_networks
                                    else "cloudflared network"
                                )
                                self.log(
                                    f"⚠️ Network Diagnostic: Container '{c_name}' is not attached to Cloudflare tunnel network '{target_net_display}'. "
                                    f"Requests to '{service_url}' will fail with 502 Bad Gateway! {plausibility.diagnostic_message}"
                                )
                                if enforce_strict_network:
                                    self.log(
                                        f"⛔ Excluding '{c_name}' from sync: STRICT_NETWORK_CHECK=true / REQUIRE_SHARED_NETWORK=true and shared network '{target_net_display}' is missing. {plausibility.diagnostic_message}"
                                    )
                                    is_tunneled = False

                            raw_policy = (
                                labels.get("cf.tunnel.access.policy")
                                or labels.get("cf.tunnel.access_policy")
                                or labels.get("cloudflared.access.policy")
                                or "unspecified"
                            )
                            access_policy = str(raw_policy).strip().lower() or "unspecified"

                            service_item: Dict[str, Any] = {
                                "name": c_name,
                                "container": c_name,
                                "hostname": hostname,
                                "service": service_url,
                                "no_tls_verify": no_tls_verify,
                                "access_policy": access_policy,
                                "network_connected": has_shared_net,
                            }
                            if not has_shared_net:
                                target_net_display = expected_network or (
                                    ", ".join(sorted(cloudflared_networks))
                                    if cloudflared_networks
                                    else "cloudflared network"
                                )
                                service_item["network_warning"] = (
                                    f"Missing shared network '{target_net_display}'. "
                                    f"Requests to {service_url} may 502 Bad Gateway. {plausibility.diagnostic_message}"
                                )
                            if origin_request:
                                service_item["originRequest"] = origin_request

                            # 6-Stage Diagnostic Pipeline (Issue #49)
                            is_hostname_valid = bool(hostname and hostname == normalized)
                            domain_matches = bool(matches_domain)
                            container_state = state.lower()

                            stages = evaluate_service_stages(
                                hostname=hostname,
                                raw_hostname=raw_hostname,
                                is_hostname_valid=is_hostname_valid,
                                domain_matches=domain_matches,
                                configured_domain=configured_domain,
                                network_connected=has_shared_net,
                                network_warning=service_item.get("network_warning"),
                                container_state=container_state,
                            )
                            service_item["stages"] = stages
                            service_item["status"] = compute_truthful_service_status(stages)

                            if is_tunneled:
                                services.append(service_item)

                    container_entry = {
                        "name": c_name,
                        "image": image,
                        "state": state,
                        "status": status_text,
                        "hostname": hostname if hostname else "-",
                        "is_tunneled": is_tunneled,
                        "network_connected": has_shared_net,
                    }
                    if is_tunneled:
                        container_entry["stages"] = stages
                        container_entry["status"] = service_item["status"]
                        container_entry["access_policy"] = service_item.get("access_policy", "unspecified")
                    else:
                        container_entry["access_policy"] = "unspecified"
                    all_containers.append(container_entry)
        except Exception as e:
            self.inventory_status = (
                InventoryStatus.UNAVAILABLE if isinstance(e, InventoryUnavailableError) else InventoryStatus.DEGRADED
            )
            self.inventory_reason = str(e)
            self.state["docker_connected"] = False
            self.log(f"Docker API Error: {e}")
            return [], []
        return services, all_containers
