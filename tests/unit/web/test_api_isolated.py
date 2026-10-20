"""Isolated API test suite running independently of UI assets (ARCH-04, Issue #115).

Verifies that the sync engine backend and REST API:
1. Function completely independently of static files, templates, or HTML assets.
2. Return proper responses even when static files are absent.
3. Keep reconciliation, diagnostics, and metrics fully operational in headless mode.
"""

import os
from unittest.mock import patch

from starlette.testclient import TestClient

import app


def test_api_operates_when_static_file_is_missing():
    """Verify that if static/index.html is deleted or missing, API endpoints still function 100%."""
    with patch("os.path.exists", return_value=False):
        client = TestClient(app.app)

        # Embedded dashboard falls back to minimal HTML instead of crashing
        with patch.dict(os.environ, {"DASHBOARD_AUTH_ENABLED": "false"}, clear=True):
            resp_root = client.get("/")
            assert resp_root.status_code == 200
            assert "Cloudflare Tunnel Sync Dashboard" in resp_root.text

            # Probes remain operational
            resp_health = client.get("/health")
            assert resp_health.status_code == 200
            assert resp_health.json()["status"] in ("healthy", "degraded")

            resp_ready = client.get("/ready")
            assert resp_ready.status_code in (200, 503)

            # API routes remain operational
            resp_status = client.get("/api/status")
            assert resp_status.status_code == 200
            assert "status" in resp_status.json()

            resp_plan = client.get("/api/change-plan")
            assert resp_plan.status_code == 200
            assert "summary" in resp_plan.json()


def test_headless_api_isolated_operations():
    """Verify backend API operations under explicit headless configuration."""
    with patch.dict(
        os.environ,
        {
            "DASHBOARD_ENABLED": "false",
            "DASHBOARD_AUTH_ENABLED": "false",
            "DOMAIN_NAME": "example.com",
            "CLOUDFLARE_TUNNEL_NAME": "headless-tunnel",
        },
        clear=True,
    ):
        app.sync_state["domain_name"] = "example.com"
        app.sync_state["tunnel_name"] = "headless-tunnel"
        client = TestClient(app.app)

        # 1. Status query
        status_resp = client.get("/api/status")
        assert status_resp.status_code == 200
        state = status_resp.json()
        assert state["domain_name"] == "example.com"
        assert state["tunnel_name"] == "headless-tunnel"

        # 2. Preview query
        preview_resp = client.get("/api/sync/preview")
        assert preview_resp.status_code == 200
        preview = preview_resp.json()
        assert preview["status"] in ("cached", "computed")

        # 3. Change plan query
        plan_resp = client.get("/api/change-plan")
        assert plan_resp.status_code == 200
        plan = plan_resp.json()
        assert "plan_id" in plan
        assert "actions" in plan

        # 4. Trigger sync
        with patch.object(app, "run_sync_logic", return_value=None):
            trigger_resp = client.post("/api/sync")
            assert trigger_resp.status_code == 200
            assert trigger_resp.json()["message"] == "Sync triggered"
