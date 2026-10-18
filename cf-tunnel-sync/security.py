"""Security hardening and credential redaction engine for cf-tunnel-sync (SEC-02)."""

import re
from typing import Any

# Common credential patterns
RE_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]+", re.IGNORECASE)
RE_DISCORD_WEBHOOK = re.compile(
    r"(https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/)[A-Za-z0-9_\-]+",
    re.IGNORECASE,
)
RE_SLACK_WEBHOOK = re.compile(
    r"(https?://hooks\.slack\.com/services/)[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+",
    re.IGNORECASE,
)
RE_GENERIC_WEBHOOK_SECRET = re.compile(
    r"(https?://[^/\s]+/[^?\s]+[?&][^#\s]*(?:token|secret|key|auth)=)[^&\s]+",
    re.IGNORECASE,
)
RE_JWT_TUNNEL_TOKEN = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
RE_HEX_SECRET_32_64 = re.compile(r"(?i)\b(?:secret|token|password|auth)[:=]\s*([a-f0-9]{32,64})\b")
RE_PARAM_CREDENTIAL = re.compile(r"(?i)\b(api_token|token|password|secret|auth_token|client_secret)=([^\s&'\"]+)")

SENSITIVE_KEY_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "auth",
    "credential",
    "api_key",
    "private_key",
)


def redact_sensitive_string(text: str) -> str:
    """Masks authorization tokens, webhook credentials, and secrets within any arbitrary string."""
    if not text or not isinstance(text, str):
        return text

    # Redact Bearer tokens
    text = RE_BEARER.sub(r"\1[REDACTED]", text)

    # Redact Discord webhook URL secrets
    text = RE_DISCORD_WEBHOOK.sub(r"\1[REDACTED]", text)

    # Redact Slack webhook URL secrets
    text = RE_SLACK_WEBHOOK.sub(r"\1[REDACTED]", text)

    # Redact Generic webhook URL query parameter secrets
    text = RE_GENERIC_WEBHOOK_SECRET.sub(r"\1[REDACTED]", text)

    # Redact JWT tokens (e.g. Cloudflare tunnel tokens)
    text = RE_JWT_TUNNEL_TOKEN.sub("[REDACTED_JWT_TOKEN]", text)

    # Redact key-value credentials (token=xyz, password=xyz)
    text = RE_PARAM_CREDENTIAL.sub(r"\1=[REDACTED]", text)

    return text


def redact_sensitive_data(data: Any) -> Any:
    """Recursively walks nested dictionaries, lists, or sets and redacts sensitive keys and string values."""
    if isinstance(data, dict):
        redacted = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(sub in k_lower for sub in SENSITIVE_KEY_SUBSTRINGS):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = redact_sensitive_data(v)
        return redacted
    elif isinstance(data, (list, tuple)):
        return [redact_sensitive_data(item) for item in data]
    elif isinstance(data, (set, frozenset)):
        return [redact_sensitive_data(item) for item in data]
    elif isinstance(data, str):
        return redact_sensitive_string(data)
    return data
