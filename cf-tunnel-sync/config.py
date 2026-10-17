"""Configuration schema validation, environment variable typo detection, and UUID checks."""

import difflib
import logging
import os
import re
import uuid
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("cf-tunnel-sync")

# Canonical known configuration environment variables
KNOWN_ENV_VARS = {
    "DOMAIN_NAME",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_TUNNEL_NAME",
    "CLOUDFLARE_TUNNEL_ID",
    "SYNC_INTERVAL",
    "ENABLE_DEBOUNCING",
    "DEBOUNCE_WAIT_SECONDS",
    "DASHBOARD_ENABLED",
    "DASHBOARD_PORT",
    "DASHBOARD_BIND_ADDRESS",
    "CF_NETWORK_NAME",
    "CLOUDFLARED_PROTOCOL",
    "DRY_RUN",
    "PREFLIGHT_ONLY",
    "MAX_DELETIONS_PER_SYNC",
    "ALLOW_MASS_DELETIONS",
    "LOG_FORMAT",
    "LOG_LEVEL",
    "NOTIFICATION_WEBHOOK_URL",
    "NOTIFICATION_WEBHOOK_TYPE",
    "NOTIFICATION_COOLDOWN_SECONDS",
    "CLOUDFLARE_MAX_RETRIES",
    "CLOUDFLARE_RETRY_BASE_DELAY",
    "DASHBOARD_AUTH_ENABLED",
    "BASIC_AUTH_USERNAME",
    "BASIC_AUTH_PASSWORD",
    "PROMETHEUS_METRICS_ENABLED",
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
)

# Historical label aliases for backward compatibility
LABEL_ALIASES: Dict[str, str] = {
    "cloudflared.hostname": "cf.tunnel.hostname",
    "cloudflared.domain": "cf.tunnel.domain",
    "cloudflared.port": "cf.tunnel.port",
    "cloudflared.service": "cf.tunnel.service",
    "cloudflared.path": "cf.tunnel.path",
    "cloudflared.enable": "cf.tunnel.enable",
    "cloudflared.access.policy": "cf.tunnel.access.policy",
    "cf.tunnel.access_policy": "cf.tunnel.access.policy",
    "cf.tunnel.no_tls_verify": "cf.tunnel.originRequest.noTLSVerify",
    "cf.tunnel.notlsverify": "cf.tunnel.originRequest.noTLSVerify",
    "cf.tunnel.originServerName": "cf.tunnel.originRequest.originServerName",
    "cf.tunnel.origin_server_name": "cf.tunnel.originRequest.originServerName",
    "cf.tunnel.httpHostHeader": "cf.tunnel.originRequest.httpHostHeader",
    "cf.tunnel.http_host_header": "cf.tunnel.originRequest.httpHostHeader",
}


def validate_tunnel_uuid(tunnel_id: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validate that CLOUDFLARE_TUNNEL_ID is a valid UUIDv4 or standard UUID.

    Returns (is_valid, error_message).
    """
    if not tunnel_id:
        return True, None

    cleaned = tunnel_id.strip()
    if not cleaned:
        return True, None

    # Check against standard UUID pattern (hex characters with hyphens)
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
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
            f"Invalid CLOUDFLARE_TUNNEL_ID '{cleaned}'. Failed UUID parsing. Must be a valid UUID.",
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
