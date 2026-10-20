"""Isolated contracts for application instances."""

from starlette.testclient import TestClient

from tests.fakes import composition
from tunnel_sync.web.app import create_http_app


def test_apps_have_independent_settings_state_and_metrics():
    first, _, _, _ = composition()
    second, _, _, _ = composition(DOMAIN_NAME="second.example")
    first.sync.run_once()
    clients = [TestClient(create_http_app(first)), TestClient(create_http_app(second))]
    assert clients[0].get("/api/status").json()["status"] == "Active / Synced"
    assert clients[1].get("/api/status").json()["status"] == "Initializing"
    assert clients[1].get("/api/status").json()["domain_name"] == "second.example"
    assert "cf_tunnel_sync_runs_total{" not in second.metrics.generate_exposition()
    snapshot = first.snapshot()
    snapshot["services"].clear()
    assert first.snapshot()["services"]
