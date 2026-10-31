"""HTTP Basic authentication, independent of synchronization."""

import logging
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

logger = logging.getLogger("cf-tunnel-sync")


def _resolve_credential(settings, primary_key: str, legacy_key: str) -> str:
    """Resolve credential value, checking primary canonical setting then legacy fallback."""
    val = settings.get(primary_key, "").strip()
    if val:
        return val
    legacy_val = settings.get(legacy_key, "").strip()
    if legacy_val:
        logger.warning(
            "Configuration note: '%s' is deprecated and will be removed in a future release. Please use '%s' instead.",
            legacy_key,
            primary_key,
        )
        return legacy_val
    return ""


def _verify_basic_credentials(credentials: Optional[HTTPBasicCredentials], user: str, pwd: str, realm: str) -> bool:
    """Validate credentials securely using constant-time comparison."""
    if not user or not pwd or not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": f'Basic realm="{realm}"'},
        )

    is_user_ok = secrets.compare_digest(credentials.username.encode("utf-8"), user.encode("utf-8"))
    is_pwd_ok = secrets.compare_digest(credentials.password.encode("utf-8"), pwd.encode("utf-8"))

    if not (is_user_ok and is_pwd_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": f'Basic realm="{realm}"'},
        )

    return True


def create_auth(get_settings):
    security = HTTPBasic(auto_error=False)

    def check_dashboard_auth(credentials: Optional[HTTPBasicCredentials] = Depends(security)) -> bool:
        settings = get_settings()
        user = _resolve_credential(settings, "DASHBOARD_USERNAME", "BASIC_AUTH_USERNAME")
        pwd = _resolve_credential(settings, "DASHBOARD_PASSWORD", "BASIC_AUTH_PASSWORD")
        auth_enabled_env = settings.get("DASHBOARD_AUTH_ENABLED", "").strip().lower()

        if auth_enabled_env in ("false", "0", "no"):
            return True

        auth_explicitly_enabled = auth_enabled_env in ("true", "1", "yes")

        if not auth_explicitly_enabled and not user and not pwd:
            return True

        return _verify_basic_credentials(credentials, user, pwd, realm="Cloudflare Tunnel Sync Dashboard")

    def check_metrics_auth(credentials: Optional[HTTPBasicCredentials] = Depends(security)) -> bool:
        """Validate HTTP Basic Auth for /metrics when METRICS_AUTH_ENABLED=true."""
        settings = get_settings()
        metrics_auth_env = settings.get("METRICS_AUTH_ENABLED", "false").strip().lower()
        if metrics_auth_env not in ("true", "1", "yes"):
            return True

        user = _resolve_credential(settings, "DASHBOARD_USERNAME", "BASIC_AUTH_USERNAME")
        pwd = _resolve_credential(settings, "DASHBOARD_PASSWORD", "BASIC_AUTH_PASSWORD")

        return _verify_basic_credentials(credentials, user, pwd, realm="Prometheus Metrics")

    return check_dashboard_auth, check_metrics_auth
