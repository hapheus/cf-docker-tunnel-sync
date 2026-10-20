"""Observed label precedence and compatibility aliases.

Lookup uses the exact historical spellings and truthy-value precedence. Registry-only
aliases remain metadata until explicitly implemented and tested through discovery.
"""

from dataclasses import dataclass
from typing import Any, Dict, Mapping

LABEL_ALIASES: Dict[str, str] = {
    # Shorthand tunnel.* prefixes
    "tunnel.hostname": "cf.tunnel.hostname",
    "tunnel.port": "cf.tunnel.port",
    "tunnel.proto": "cf.tunnel.proto",
    "tunnel.protocol": "cf.tunnel.protocol",
    "tunnel.service": "cf.tunnel.service",
    "tunnel.notlsverify": "cf.tunnel.originRequest.noTLSVerify",
    # cloudflared.* legacy prefix
    "cloudflared.hostname": "cf.tunnel.hostname",
    "cloudflared.domain": "cf.tunnel.domain",
    "cloudflared.port": "cf.tunnel.port",
    "cloudflared.proto": "cf.tunnel.proto",
    "cloudflared.protocol": "cf.tunnel.protocol",
    "cloudflared.scheme": "cf.tunnel.scheme",
    "cloudflared.service": "cf.tunnel.service",
    "cloudflared.path": "cf.tunnel.path",
    "cloudflared.enable": "cf.tunnel.enable",
    "cloudflared.name": "cf.tunnel.name",
    "cloudflared.tunnel": "cf.tunnel.name",
    "cloudflared.access.policy": "cf.tunnel.access.policy",
    "cloudflared.notlsverify": "cf.tunnel.originRequest.noTLSVerify",
    "cloudflared.notls_verify": "cf.tunnel.originRequest.noTLSVerify",
    "cloudflared.origin_server_name": "cf.tunnel.originRequest.originServerName",
    # cftunnel.* legacy shorthand prefix
    "cftunnel.hostname": "cf.tunnel.hostname",
    "cftunnel.domain": "cf.tunnel.domain",
    "cftunnel.port": "cf.tunnel.port",
    "cftunnel.proto": "cf.tunnel.proto",
    "cftunnel.protocol": "cf.tunnel.protocol",
    "cftunnel.scheme": "cf.tunnel.scheme",
    "cftunnel.service": "cf.tunnel.service",
    "cftunnel.path": "cf.tunnel.path",
    "cftunnel.enable": "cf.tunnel.enable",
    "cftunnel.name": "cf.tunnel.name",
    "cftunnel.tunnel": "cf.tunnel.name",
    "cftunnel.access.policy": "cf.tunnel.access.policy",
    "cftunnel.notlsverify": "cf.tunnel.originRequest.noTLSVerify",
    "cftunnel.notls_verify": "cf.tunnel.originRequest.noTLSVerify",
    "cftunnel.origin_server_name": "cf.tunnel.originRequest.originServerName",
    # Shorthand single word aliases
    "proto": "cf.tunnel.proto",
    "port": "cf.tunnel.port",
    "notlsverify": "cf.tunnel.originRequest.noTLSVerify",
    "origin_server_name": "cf.tunnel.originRequest.originServerName",
    # Alternative casings and variations
    "cf.tunnel.access_policy": "cf.tunnel.access.policy",
    "cf.tunnel.no_tls_verify": "cf.tunnel.originRequest.noTLSVerify",
    "cf.tunnel.notlsverify": "cf.tunnel.originRequest.noTLSVerify",
    "cf.tunnel.originServerName": "cf.tunnel.originRequest.originServerName",
    "cf.tunnel.origin_server_name": "cf.tunnel.originRequest.originServerName",
    "cf.tunnel.originrequest.originservername": "cf.tunnel.originRequest.originServerName",
    "http_host_header": "cf.tunnel.originRequest.httpHostHeader",
    "cf.tunnel.httpHostHeader": "cf.tunnel.originRequest.httpHostHeader",
    "cf.tunnel.http_host_header": "cf.tunnel.originRequest.httpHostHeader",
    "cf.tunnel.originrequest.httphostheader": "cf.tunnel.originRequest.httpHostHeader",
}


LEGACY_LABEL_CANONICAL_MAP = {
    "cloudflared.hostname": "cf.tunnel.hostname",
    "cloudflared.domain": "cf.tunnel.domain",
    "cloudflared.port": "cf.tunnel.port",
    "cloudflared.service": "cf.tunnel.service",
    "cloudflared.proto": "cf.tunnel.proto",
    "cloudflared.protocol": "cf.tunnel.protocol",
    "cloudflared.scheme": "cf.tunnel.scheme",
    "cloudflared.name": "cf.tunnel.name",
    "cloudflared.tunnel": "cf.tunnel.name",
    "cloudflared.notlsverify": "cf.tunnel.origin_request.no_tls_verify",
    "cloudflared.notls_verify": "cf.tunnel.origin_request.no_tls_verify",
    "cloudflared.originRequest.noTLSVerify": "cf.tunnel.origin_request.no_tls_verify",
    "cloudflared.origin_request.no_tls_verify": "cf.tunnel.origin_request.no_tls_verify",
    "cloudflared.httpHostHeader": "cf.tunnel.origin_request.http_host_header",
    "cloudflared.originRequest.httpHostHeader": "cf.tunnel.origin_request.http_host_header",
    "port": "cf.tunnel.port",
    "proto": "cf.tunnel.proto",
    "protocol": "cf.tunnel.protocol",
    "scheme": "cf.tunnel.scheme",
    "notlsverify": "cf.tunnel.origin_request.no_tls_verify",
    "cloudflared.host": "cf.tunnel.hostname",
    "cf.tunnel.host": "cf.tunnel.hostname",
    "hostname": "cf.tunnel.hostname",
    "host": "cf.tunnel.hostname",
}


LABEL_PRECEDENCE = {
    "cf.tunnel.hostname": (
        "cf.tunnel.hostname",
        "cf.tunnel.domain",
        "cf.tunnel.host",
        "cloudflared.hostname",
        "cloudflared.domain",
        "cloudflared.host",
        "hostname",
        "host",
    ),
    "cf.tunnel.name": ("cf.tunnel.name", "cf.tunnel.tunnel", "cloudflared.name", "cloudflared.tunnel"),
    "cf.tunnel.port": ("cf.tunnel.port", "cloudflared.port", "port"),
    "cf.tunnel.service": ("cf.tunnel.service", "cloudflared.service"),
    "cf.tunnel.originServerName": (
        "cf.tunnel.originServerName",
        "cf.tunnel.origin.server.name",
        "cf.tunnel.origin_server_name",
        "cloudflared.originServerName",
        "cloudflared.origin.server.name",
        "cloudflared.origin_server_name",
    ),
    "cf.tunnel.httpHostHeader": (
        "cf.tunnel.httpHostHeader",
        "cf.tunnel.http.host.header",
        "cf.tunnel.http_host_header",
        "cloudflared.httpHostHeader",
        "cloudflared.http.host.header",
        "cloudflared.http_host_header",
    ),
    "cf.tunnel.notlsverify": (
        "cf.tunnel.notlsverify",
        "cf.tunnel.notls_verify",
        "cf.tunnel.originRequest.noTLSVerify",
        "cf.tunnel.origin_request.no_tls_verify",
    ),
    "cf.tunnel.tls.verify": ("cf.tunnel.tls.verify", "cf.tunnel.tls_verify"),
    "cloudflared.notlsverify": (
        "cloudflared.notlsverify",
        "cloudflared.notls_verify",
        "cloudflared.originRequest.noTLSVerify",
        "cloudflared.origin_request.no_tls_verify",
    ),
    "cloudflared.tls.verify": ("cloudflared.tls.verify", "cloudflared.tls_verify"),
    "notlsverify": ("notlsverify", "no_tls_verify"),
}


def first_label(labels: Mapping[str, Any], group: str):
    for key in LABEL_PRECEDENCE[group]:
        value = labels.get(key)
        if value:
            return value
    return None


def resolve_canonical_label(label_key: str) -> str:
    cleaned = label_key.strip()
    return LABEL_ALIASES.get(cleaned, cleaned)


@dataclass(frozen=True)
class ParsedOrigin:
    service_target: str
    origin_request: dict[str, Any]
    no_tls_verify: bool
    warnings: tuple[str, ...] = ()


def parse_origin_labels(labels: Mapping[str, Any], c_name: str, ports: Any) -> ParsedOrigin:
    """Parse service/TLS options without Docker, environment, logging, or state."""
    warnings: list[str] = []
    # Protocol / Scheme (precedence: modern cf.tunnel.* > legacy cloudflared.* > bare shorthand)
    raw_proto = (
        labels.get("cf.tunnel.protocol")
        or labels.get("cf.tunnel.proto")
        or labels.get("cf.tunnel.scheme")
        or labels.get("cloudflared.protocol")
        or labels.get("cloudflared.proto")
        or labels.get("cloudflared.scheme")
        or labels.get("proto")
        or labels.get("protocol")
        or labels.get("scheme")
        or "http"
    )
    proto = str(raw_proto).strip().lower()
    if proto not in ("http", "https", "tcp", "udp", "ssh", "rdp"):
        proto = "http"

    # Port parsing and validation (precedence: modern > legacy > bare shorthand)
    port_label = first_label(labels, "cf.tunnel.port")
    valid_port = None
    if port_label:
        port_str = str(port_label).strip()
        if port_str.isdigit():
            p_int = int(port_str)
            if 1 <= p_int <= 65535:
                valid_port = p_int
            else:
                warnings.append(f"⚠️ Port {p_int} for container '{c_name}' out of range (1-65535)")
        else:
            warnings.append(f"⚠️ Non-numeric port '{port_label}' for container '{c_name}'")

    # Service URL assembly (precedence: modern > legacy)
    explicit_service = first_label(labels, "cf.tunnel.service")
    if explicit_service and str(explicit_service).strip():
        service_url = str(explicit_service).strip()
    elif valid_port is not None:
        service_url = f"{proto}://{c_name}:{valid_port}"
    else:
        inspected_port = None
        if isinstance(ports, list) and ports and isinstance(ports[0], dict):
            ip = ports[0].get("PrivatePort")
            if isinstance(ip, int) and 1 <= ip <= 65535:
                inspected_port = ip
        if inspected_port:
            service_url = f"{proto}://{c_name}:{inspected_port}"
        else:
            default_port = 443 if proto == "https" else 80
            service_url = f"{proto}://{c_name}:{default_port}"

    # Origin request & TLS settings
    origin_request: Dict[str, Any] = {}
    no_tls_verify = False

    def _parse_bool(v):
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("true", "1", "yes"):
            return True
        if s in ("false", "0", "no"):
            return False
        return None

    # Precedence: modern cf.tunnel.* > legacy cloudflared.* > bare shorthand
    modern_notls = _parse_bool(first_label(labels, "cf.tunnel.notlsverify"))
    modern_tls = _parse_bool(first_label(labels, "cf.tunnel.tls.verify"))

    legacy_notls = _parse_bool(first_label(labels, "cloudflared.notlsverify"))
    legacy_tls = _parse_bool(first_label(labels, "cloudflared.tls.verify"))

    shorthand_notls = _parse_bool(first_label(labels, "notlsverify"))
    shorthand_tls = _parse_bool(labels.get("tls_verify"))

    if modern_notls is not None:
        no_tls_verify = modern_notls
    elif modern_tls is not None:
        no_tls_verify = not modern_tls
    elif legacy_notls is not None:
        no_tls_verify = legacy_notls
    elif legacy_tls is not None:
        no_tls_verify = not legacy_tls
    elif shorthand_notls is not None:
        no_tls_verify = shorthand_notls
    elif shorthand_tls is not None:
        no_tls_verify = not shorthand_tls
    else:
        no_tls_verify = False

    if no_tls_verify:
        origin_request["noTLSVerify"] = True

    # Origin Server Name override (modern > legacy)
    origin_server_name = first_label(labels, "cf.tunnel.originServerName")
    if origin_server_name and str(origin_server_name).strip():
        origin_request["originServerName"] = str(origin_server_name).strip()

    # HTTP host header override (modern > legacy)
    http_host_header = first_label(labels, "cf.tunnel.httpHostHeader")
    if http_host_header and str(http_host_header).strip():
        origin_request["httpHostHeader"] = str(http_host_header).strip()

    return ParsedOrigin(service_url, origin_request, no_tls_verify, tuple(warnings))
