"""Configuration schema validation, environment variable typo detection, and UUID checks."""

import difflib
import logging
import os
import re
import uuid
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("cf-tunnel-sync")

# Canonical known configuration environment variables and backward-compatible aliases
KNOWN_ENV_VARS = {
    # Core Cloudflare credentials and tunnel target
    "DOMAIN_NAME",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_ZONE_ID",
    "CLOUDFLARE_TUNNEL_NAME",
    "TUNNEL_NAME",
    "CLOUDFLARE_TUNNEL_ID",
    "CLOUDFLARE_DNS_PROXIED",
    "PROXIED",
    "AUTO_CREATE_TUNNEL",
    "CLOUDFLARED_CONTAINER_NAME",
    # Docker network and synchronization
    "REQUIRE_SHARED_NETWORK",
    "STRICT_NETWORK_CHECK",
    "CF_NETWORK_NAME",
    "CUSTOM_NETWORK",
    "SYNC_INTERVAL",
    "POLL_INTERVAL",
    "SYNC_FALLBACK_INTERVAL",
    "FALLBACK_INTERVAL",
    "ENABLE_DEBOUNCING",
    "DEBOUNCE_WAIT_SECONDS",
    "DEBOUNCE_SECONDS",
    "SYNC_DEBOUNCE_DELAY",
    "SYNC_DEBOUNCE_MAX_DELAY",
    "SYNC_DEBOUNCE_SECONDS",
    "INITIAL_DELAY",
    # Dashboard and API exposure
    "DASHBOARD_ENABLED",
    "DASHBOARD_PORT",
    "PORT",
    "DASHBOARD_BIND_ADDRESS",
    "DASHBOARD_AUTH_ENABLED",
    "DASHBOARD_USERNAME",
    "DASHBOARD_PASSWORD",
    "BASIC_AUTH_USERNAME",
    "BASIC_AUTH_PASSWORD",
    "PROMETHEUS_METRICS_ENABLED",
    "PROMETHEUS_PORT",
    "STRICT_HEALTH_STATUS",
    # Protocol, safety, and operations
    "CLOUDFLARED_PROTOCOL",
    "DRY_RUN",
    "PREFLIGHT_ONLY",
    "ENABLE_CHANGE_PLAN",
    "MAX_DELETIONS_PER_SYNC",
    "MAX_DELETIONS_THRESHOLD",
    "MAX_DELETIONS_PER_RUN",
    "MAX_DELETION_RATIO",
    "ALLOW_MASS_DELETIONS",
    "OWNERSHIP_POLICY",
    "DNS_CLEANUP_GRACE_PERIOD",
    "DNS_IMMEDIATE_CLEANUP",
    "LOG_FORMAT",
    "LOG_LEVEL",
    "HOST_IP",
    # Resilience, retry, and notifications
    "DOCKER_SOCKET",
    "DOCKER_SOCKET_PATH",
    "DOCKER_TIMEOUT",
    "DOCKER_RETRIES",
    "CLOUDFLARE_MAX_RETRIES",
    "CLOUDFLARE_RETRY_BASE_DELAY",
    "NOTIFICATION_WEBHOOK_URL",
    "NOTIFICATION_WEBHOOK_TYPE",
    "NOTIFICATION_COOLDOWN_SECONDS",
}

# Prefixes that strongly indicate an intended configuration setting
CONFIG_PREFIXES = (
    "CLOUDFLARE_",
    "CF_",
    "DASHBOARD_",
    "SYNC_",
    "DEBOUNCE_",
    "NOTIFICATION_",
    "PREFLIGHT_",
    "MAX_DELETIONS_",
    "ALLOW_MASS_",
    "LOG_",
    "BASIC_AUTH_",
)

# Historical label aliases for backward compatibility (100% frozen coverage)
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


def validate_tunnel_uuid(tunnel_id: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validate that CLOUDFLARE_TUNNEL_ID is a well-formed UUID string if provided.

    Returns (is_valid, error_message). Empty or None is considered valid (optional).
    """
    if not tunnel_id:
        return True, None

    cleaned = tunnel_id.strip()
    if not cleaned:
        return True, None

    # Check against standard UUID pattern (hex characters with hyphens)
    uuid_pattern = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    )
    if not uuid_pattern.match(cleaned):
        return (
            False,
            f"Invalid CLOUDFLARE_TUNNEL_ID '{cleaned}'. "
            "Must be a valid UUID formatted as xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.",
        )

    try:
        uuid.UUID(cleaned)
        return True, None
    except ValueError:
        return (
            False,
            f"Invalid CLOUDFLARE_TUNNEL_ID '{cleaned}'. Failed UUID parsing. Must be a valid UUID formatted as xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.",
        )


def detect_env_typos(env_dict: Optional[Dict[str, str]] = None) -> List[str]:
    """Inspect environment variables for likely typos of known configuration options.

    Returns a list of warning messages.
    """
    if env_dict is None:
        env_dict = dict(os.environ)

    warnings: List[str] = []

    for key in env_dict.keys():
        if key in KNOWN_ENV_VARS:
            continue

        # Check if key starts with a known config prefix or looks like a typo
        is_candidate = any(key.startswith(p) for p in CONFIG_PREFIXES)
        if not is_candidate:
            # Also check if it's closely matching a known var even without prefix
            close_matches = difflib.get_close_matches(key, KNOWN_ENV_VARS, n=1, cutoff=0.75)
            if close_matches:
                is_candidate = True

        if is_candidate:
            matches = difflib.get_close_matches(key, KNOWN_ENV_VARS, n=1, cutoff=0.6)
            if matches:
                warning = f"Unknown configuration variable '{key}' detected. Did you mean '{matches[0]}'?"
            else:
                warning = f"Unknown configuration variable '{key}' with recognized prefix detected."
            warnings.append(warning)
            logger.warning(warning)

    return warnings


def resolve_canonical_label(label_key: str) -> str:
    """Resolve historical or shorthand label key to canonical cf.tunnel.* key."""
    cleaned = label_key.strip()
    return LABEL_ALIASES.get(cleaned, cleaned)
