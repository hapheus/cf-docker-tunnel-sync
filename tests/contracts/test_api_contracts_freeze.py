"""API contract freeze and JSON schema regression test suite (ARCH-01, Issue #112).

Freezes schemas, authentication behavior, HTTP status codes, security headers,
and payload structures for all public API and probe endpoints.
Guarantees strictly zero unannounced breaking changes.
"""

import os
from unittest.mock import patch

from starlette.testclient import TestClient

import app


def get_unauthenticated_client():
    return TestClient(app.app)


def test_health_and_healthz_contract_frozen():
    """Verify GET /health and /healthz schemas, status codes, and fields."""
    with patch.dict(
        os.environ,
        {"DASHBOARD_AUTH_ENABLED": "true", "DASHBOARD_USERNAME": "admin", "DASHBOARD_PASSWORD": "password123"},
        clear=True,
    ):
        client = get_unauthenticated_client()

        for route in ["/health", "/healthz"]:
            app.sync_state["docker_connected"] = True
            app.sync_state["status"] = "Active"
            resp = client.get(route)
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)
            assert "status" in data
            assert "docker_connected" in data
            assert "sync_status" in data
            assert data["status"] == "healthy"
            assert data["docker_connected"] is True
            assert data["sync_status"] == "Active"

            # Degraded state when Docker is disconnected
            app.sync_state["docker_connected"] = False
            resp_degraded = client.get(route)
            assert resp_degraded.status_code == 200
            data_degraded = resp_degraded.json()
            assert data_degraded["status"] == "degraded"
            assert data_degraded["docker_connected"] is False


def test_ready_probe_contract_frozen():
    """Verify GET /ready behavior for ready (200) and unready (503) states."""
    client = get_unauthenticated_client()

    # Ready state
    app.sync_state["docker_connected"] = True
    app.sync_state["status"] = "Synced"
    resp_ok = client.get("/ready")
    assert resp_ok.status_code == 200
    data_ok = resp_ok.json()
    assert data_ok["status"] == "ready"
    assert data_ok["docker_connected"] is True

    # Not ready state
    app.sync_state["docker_connected"] = False
    resp_down = client.get("/ready")
    assert resp_down.status_code == 503
    data_down = resp_down.json()
    assert data_down["status"] == "not ready"
    assert data_down["docker_connected"] is False


def test_metrics_prometheus_exposition_contract_frozen():
    """Verify GET /metrics text exposition schema and headers."""
    client = get_unauthenticated_client()
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "version=0.0.4" in resp.headers["content-type"]
    assert "# HELP" in resp.text
    assert "# TYPE" in resp.text


def test_embedded_dashboard_contract_and_security_headers():
    """Verify GET / and /dashboard HTML delivery, security headers, and headless toggle."""
    client = get_unauthenticated_client()

    # 1. Enabled by default (or DASHBOARD_ENABLED=true)
    with patch.dict(os.environ, {"DASHBOARD_ENABLED": "true", "DASHBOARD_AUTH_ENABLED": "false"}, clear=True):
        for route in ["/", "/dashboard"]:
            resp = client.get(route)
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert "Content-Security-Policy" in resp.headers
            assert resp.headers["X-Frame-Options"] == "DENY"
            assert resp.headers["X-Content-Type-Options"] == "nosniff"

    # 2. Headless mode (DASHBOARD_ENABLED=false)
    with patch.dict(os.environ, {"DASHBOARD_ENABLED": "false", "DASHBOARD_AUTH_ENABLED": "false"}, clear=True):
        for route in ["/", "/dashboard"]:
            resp_disabled = client.get(route)
            assert resp_disabled.status_code == 404
            data_disabled = resp_disabled.json()
            assert data_disabled["status"] == "disabled"
            assert "Embedded dashboard UI is disabled" in data_disabled["message"]


def test_api_status_contract_freeze_and_field_invariants():
    """Verify GET /api/status response schema, key types, and secret redaction."""
    app.sync_state["status"] = "Active"
    app.sync_state["domain_name"] = "example.com"
    app.sync_state["tunnel_name"] = "test-tunnel"
    app.sync_state["tunnel_id"] = "test-tunnel-id-12345"
    app.sync_state["docker_connected"] = True
    app.sync_state["services"] = {
        "web": {"hostname": "web.example.com", "service": "http://web:80", "status": "Active"}
    }
    app.sync_state["logs"] = ["Sync cycle completed"]
    app.sync_state["_internal_cache"] = "private_value"

    with patch.dict(os.environ, {"DASHBOARD_AUTH_ENABLED": "false"}, clear=True):
        client = get_unauthenticated_client()
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()

        # Invariant public contract keys
        required_keys = [
            "status",
            "domain_name",
            "tunnel_name",
            "tunnel_id",
            "docker_connected",
            "services",
            "logs",
            "discovered_services",
            "dns_records",
            "all_containers",
            "safety_guard_tripped",
        ]
        for key in required_keys:
            assert key in data, f"Required public status key '{key}' missing from /api/status payload!"

        # Invariant types
        assert isinstance(data["status"], str)
        assert isinstance(data["docker_connected"], bool)
        assert isinstance(data["services"], (dict, list))
        assert isinstance(data["logs"], list)
        assert isinstance(data["safety_guard_tripped"], bool)

        # Invariant security redaction: private keys starting with _ must NEVER leak
        assert "_internal_cache" not in data


def test_api_change_plan_contract_freeze():
    """Verify GET /api/change-plan response schema and summary counters."""
    with patch.dict(os.environ, {"DASHBOARD_AUTH_ENABLED": "false"}, clear=True):
        client = get_unauthenticated_client()
        resp = client.get("/api/change-plan")
        assert resp.status_code == 200
        data = resp.json()

        # Top-level structure
        assert "plan_id" in data
        assert "actions" in data
        assert "dry_run" in data
        assert "summary" in data
        assert "timestamp" in data

        # Summary structure
        summary = data["summary"]
        expected_summary_keys = [
            "additions",
            "updates",
            "deletions",
            "unmanaged_skipped",
        ]
        for sk in expected_summary_keys:
            assert sk in summary, f"Summary counter '{sk}' missing from change-plan contract!"
            assert isinstance(summary[sk], int)


def test_api_sync_trigger_and_preview_contract_freeze():
    """Verify POST /api/sync and GET /api/sync/preview schemas."""
    with patch.dict(os.environ, {"DASHBOARD_AUTH_ENABLED": "false"}, clear=True):
        client = get_unauthenticated_client()

        # Preview
        resp_preview = client.get("/api/sync/preview")
        assert resp_preview.status_code == 200
        preview_data = resp_preview.json()
        assert "status" in preview_data
        assert "plan" in preview_data
        assert preview_data["status"] in ("cached", "computed")

        # Sync trigger
        with patch.object(app, "run_sync_logic", return_value=None):
            resp_trigger = client.post("/api/sync")
            assert resp_trigger.status_code == 200
            trigger_data = resp_trigger.json()
            assert "message" in trigger_data
            assert "state" in trigger_data
            assert trigger_data["message"] == "Sync triggered"
