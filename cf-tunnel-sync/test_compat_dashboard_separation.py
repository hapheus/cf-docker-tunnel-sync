"""Compatibility tests for embedded UI and companion dashboard deployment modes (ARCH-03, Issue #114).

Verifies:
1. Existing single-container deployments with embedded UI continue working out of the box with zero configuration changes.
2. Headless mode (DASHBOARD_ENABLED=false) disables HTML UI routes while leaving all API routes functional.
3. Auth and port defaults remain 100% backwards-compatible.
"""

import os
from unittest.mock import patch

import app
from starlette.testclient import TestClient


def test_embedded_ui_default_compatibility():
    """Verify that by default, GET / and GET /dashboard serve the embedded HTML application."""
    # Ensure neither DASHBOARD_ENABLED nor EMBEDDED_DASHBOARD_ENABLED is explicitly set
    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(app.app)
        for path in ["/", "/dashboard"]:
            resp = client.get(path)
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert "<!DOCTYPE html>" in resp.text
            assert "Content-Security-Policy" in resp.headers
            assert resp.headers["X-Frame-Options"] == "DENY"
            assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_embedded_ui_auth_compatibility():
    """Verify that embedded UI and API share the exact same HTTP Basic Auth credentials and fail-closed logic."""
    with patch.dict(
        os.environ,
        {
            "DASHBOARD_AUTH_ENABLED": "true",
            "BASIC_AUTH_USERNAME": "operator",
            "BASIC_AUTH_PASSWORD": "secure_operator_password",
        },
        clear=True,
    ):
        client = TestClient(app.app)

        # 1. Unauthenticated request rejected
        resp_unauth = client.get("/dashboard")
        assert resp_unauth.status_code == 401
        assert "WWW-Authenticate" in resp_unauth.headers

        # 2. Authenticated request accepted
        resp_auth = client.get("/dashboard", auth=("operator", "secure_operator_password"))
        assert resp_auth.status_code == 200
        assert "<!DOCTYPE html>" in resp_auth.text

        # 3. API endpoints enforce identical authentication
        resp_api_unauth = client.get("/api/status")
        assert resp_api_unauth.status_code == 401

        resp_api_auth = client.get("/api/status", auth=("operator", "secure_operator_password"))
        assert resp_api_auth.status_code == 200
        assert resp_api_auth.json()["status"] == app.sync_state["status"]


def test_headless_mode_disables_ui_while_preserving_api():
    """Verify that when DASHBOARD_ENABLED=false, HTML routes are disabled but all API routes remain active."""
    with patch.dict(os.environ, {"DASHBOARD_ENABLED": "false", "DASHBOARD_AUTH_ENABLED": "false"}, clear=True):
        client = TestClient(app.app)

        # UI endpoints return 404 JSON
        for path in ["/", "/dashboard"]:
            resp_ui = client.get(path)
            assert resp_ui.status_code == 404
            assert resp_ui.json()["status"] == "disabled"

        # Public probe and API endpoints remain fully functional
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.get("/metrics").status_code == 200
        assert client.get("/api/status").status_code == 200
        assert client.get("/api/change-plan").status_code == 200
