"""HTTP Basic authentication, independent of synchronization."""

import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials


def create_auth(get_settings):
    security = HTTPBasic(auto_error=False)

    def check_dashboard_auth(credentials: Optional[HTTPBasicCredentials] = Depends(security)) -> bool:
        settings = get_settings()
        user = settings.get("DASHBOARD_USERNAME", settings.get("BASIC_AUTH_USERNAME", "")).strip()
        pwd = settings.get("DASHBOARD_PASSWORD", settings.get("BASIC_AUTH_PASSWORD", "")).strip()
        auth_enabled_env = settings.get("DASHBOARD_AUTH_ENABLED", "").strip().lower()

        if auth_enabled_env in ("false", "0", "no"):
            return True

        auth_explicitly_enabled = auth_enabled_env in ("true", "1", "yes")

        if not auth_explicitly_enabled and not user and not pwd:
            return True

        # Fail-closed: Auth is enabled, but credentials are blank or unconfigured
        if not user or not pwd:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": 'Basic realm="Cloudflare Tunnel Sync Dashboard"'},
            )

        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": 'Basic realm="Cloudflare Tunnel Sync Dashboard"'},
            )

        is_user_ok = secrets.compare_digest(credentials.username.encode("utf-8"), user.encode("utf-8"))
        is_pwd_ok = secrets.compare_digest(credentials.password.encode("utf-8"), pwd.encode("utf-8"))

        if not (is_user_ok and is_pwd_ok):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": 'Basic realm="Cloudflare Tunnel Sync Dashboard"'},
            )

        return True

    def check_metrics_auth(credentials: Optional[HTTPBasicCredentials] = Depends(security)) -> bool:
        """Validate HTTP Basic Auth for /metrics when METRICS_AUTH_ENABLED=true (Issue #123).

        Defaults to false to maintain 100% backward compatibility with existing Prometheus scrapers.
        """
        settings = get_settings()
        metrics_auth_env = settings.get("METRICS_AUTH_ENABLED", "false").strip().lower()
        if metrics_auth_env not in ("true", "1", "yes"):
            return True

        user = settings.get("DASHBOARD_USERNAME", settings.get("BASIC_AUTH_USERNAME", "")).strip()
        pwd = settings.get("DASHBOARD_PASSWORD", settings.get("BASIC_AUTH_PASSWORD", "")).strip()

        if not user or not pwd or not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": 'Basic realm="Prometheus Metrics"'},
            )

        is_user_ok = secrets.compare_digest(credentials.username.encode("utf-8"), user.encode("utf-8"))
        is_pwd_ok = secrets.compare_digest(credentials.password.encode("utf-8"), pwd.encode("utf-8"))

        if not (is_user_ok and is_pwd_ok):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": 'Basic realm="Prometheus Metrics"'},
            )

        return True

    return check_dashboard_auth, check_metrics_auth
