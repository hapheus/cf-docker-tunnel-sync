"""Comprehensive Observability & Dashboard Metrics Suite (Milestone 4, Issues #116-#124).

Covers:
- Issue #116: Prometheus metrics expansion (latency, error rates, operation counters)
- Issue #117: High-level status cards in dashboard API (health states, counts)
- Issue #118 & #123: Authenticated Prometheus scraping option with zero breaking changes
- Issue #119: Sync duration and run history ring-buffer (/api/history)
- Issue #120: Searchable event timeline with redaction (/api/events)
- Issue #121: Webhook alert delivery status indicator (/api/notifications/status)
- Issue #122: Service diagnostic breakdown in UI (stage pills & actionable hints)
- Issue #124: End-to-end observability test suite verification
"""

import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import app
from metrics import PrometheusRegistry
from notifications import NotificationDispatcher
from tests.paths import REPO_ROOT


class TestObservabilityMetricsExpansion(unittest.TestCase):
    """Issue #116: Prometheus metrics expansion."""

    def setUp(self):
        self.reg = PrometheusRegistry()

    def test_metrics_registration_and_types(self):
        """All expanded metric types and help texts are registered correctly."""
        expo = self.reg.generate_exposition()
        self.assertIn("# HELP cf_tunnel_sync_last_success_timestamp", expo)
        self.assertIn("# TYPE cf_tunnel_sync_last_success_timestamp gauge", expo)
        self.assertIn("# HELP cf_tunnel_sync_failures_total", expo)
        self.assertIn("# TYPE cf_tunnel_sync_failures_total counter", expo)
        self.assertIn("# HELP cf_tunnel_dns_operations_total", expo)
        self.assertIn("# TYPE cf_tunnel_dns_operations_total counter", expo)
        self.assertIn("# HELP cf_tunnel_ingress_operations_total", expo)
        self.assertIn("# TYPE cf_tunnel_ingress_operations_total counter", expo)
        self.assertIn("# HELP cf_tunnel_docker_connected", expo)
        self.assertIn("# TYPE cf_tunnel_docker_connected gauge", expo)
        self.assertIn("# HELP cf_tunnel_webhook_deliveries_total", expo)
        self.assertIn("# TYPE cf_tunnel_webhook_deliveries_total counter", expo)
        self.assertIn("# HELP cf_tunnel_cloudflare_errors_total", expo)
        self.assertIn("# TYPE cf_tunnel_cloudflare_errors_total counter", expo)

    def test_record_dns_and_ingress_operations(self):
        """Operation counters properly record labeled operations."""
        self.reg.record_dns_op("create", 2.0)
        self.reg.record_dns_op("update", 1.0)
        self.reg.record_dns_op("delete", 3.0)
        self.reg.record_dns_op("protect", 4.0)

        self.reg.record_ingress_op("update", 1.0)
        self.reg.record_ingress_op("failed", 2.0)

        expo = self.reg.generate_exposition()
        self.assertIn('cf_tunnel_dns_operations_total{operation="create"} 2.0', expo)
        self.assertIn('cf_tunnel_dns_operations_total{operation="update"} 1.0', expo)
        self.assertIn('cf_tunnel_dns_operations_total{operation="delete"} 3.0', expo)
        self.assertIn('cf_tunnel_dns_operations_total{operation="protect"} 4.0', expo)
        self.assertIn('cf_tunnel_ingress_operations_total{operation="update"} 1.0', expo)
        self.assertIn('cf_tunnel_ingress_operations_total{operation="failed"} 2.0', expo)

    def test_record_sync_run_success_and_failure(self):
        """Record sync run updates timestamp on success and failure counter on error."""
        self.reg.record_sync_run(duration=0.45, status="success", discovered_count=3)
        expo = self.reg.generate_exposition()
        self.assertIn("cf_tunnel_sync_duration_seconds 0.45", expo)
        self.assertIn("cf_tunnel_services_discovered 3.0", expo)
        self.assertIn('cf_tunnel_sync_runs_total{status="success"} 1.0', expo)

        # Fail run
        self.reg.record_sync_run(duration=1.2, status="error", discovered_count=0)
        expo_fail = self.reg.generate_exposition()
        self.assertIn('cf_tunnel_sync_runs_total{status="error"} 1.0', expo_fail)
        self.assertIn("cf_tunnel_sync_failures_total 1.0", expo_fail)

    def test_record_webhook_and_cf_errors(self):
        """Webhook delivery and Cloudflare API error counts are recorded."""
        self.reg.record_webhook_delivery("success")
        self.reg.record_webhook_delivery("failure")
        self.reg.record_cloudflare_error(429)
        self.reg.record_cloudflare_error(500)

        expo = self.reg.generate_exposition()
        self.assertIn('cf_tunnel_webhook_deliveries_total{status="success"} 1.0', expo)
        self.assertIn('cf_tunnel_webhook_deliveries_total{status="failure"} 1.0', expo)
        self.assertIn('cf_tunnel_cloudflare_errors_total{status_code="429"} 1.0', expo)
        self.assertIn('cf_tunnel_cloudflare_errors_total{status_code="500"} 1.0', expo)


class TestPrometheusScraperAuth(unittest.TestCase):
    """Issue #118 & #123: Zero breaking changes for Prometheus scrapers & optional Basic Auth."""

    def setUp(self):
        self.client = TestClient(app.app)

    def test_metrics_unauthenticated_by_default(self):
        """Strictly zero breaking changes: /metrics is public by default without credentials."""
        with patch.dict(os.environ, {"METRICS_AUTH_ENABLED": "false"}, clear=False):
            resp = self.client.get("/metrics")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("text/plain", resp.headers["content-type"])
            self.assertIn("cf_tunnel_sync_runs_total", resp.text)

    def test_metrics_authenticated_mode_rejects_missing_credentials(self):
        """When METRICS_AUTH_ENABLED=true, unauthenticated requests are rejected with 401."""
        with patch.dict(
            os.environ,
            {
                "METRICS_AUTH_ENABLED": "true",
                "DASHBOARD_USERNAME": "metricsadmin",
                "DASHBOARD_PASSWORD": "secretpassword",
            },
            clear=False,
        ):
            resp = self.client.get("/metrics")
            self.assertEqual(resp.status_code, 401)
            self.assertIn('Basic realm="Prometheus Metrics"', resp.headers.get("www-authenticate", ""))

    def test_metrics_authenticated_mode_accepts_valid_credentials(self):
        """When METRICS_AUTH_ENABLED=true, requests with valid credentials succeed."""
        with patch.dict(
            os.environ,
            {
                "METRICS_AUTH_ENABLED": "true",
                "DASHBOARD_USERNAME": "metricsadmin",
                "DASHBOARD_PASSWORD": "secretpassword",
            },
            clear=False,
        ):
            resp = self.client.get("/metrics", auth=("metricsadmin", "secretpassword"))
            self.assertEqual(resp.status_code, 200)
            self.assertIn("cf_tunnel_sync_runs_total", resp.text)

    def test_metrics_authenticated_mode_rejects_wrong_credentials(self):
        """When METRICS_AUTH_ENABLED=true, incorrect credentials return 401."""
        with patch.dict(
            os.environ,
            {
                "METRICS_AUTH_ENABLED": "true",
                "DASHBOARD_USERNAME": "metricsadmin",
                "DASHBOARD_PASSWORD": "secretpassword",
            },
            clear=False,
        ):
            resp = self.client.get("/metrics", auth=("metricsadmin", "wrongpassword"))
            self.assertEqual(resp.status_code, 401)


class TestOverviewMetricsAndHealthState(unittest.TestCase):
    """Issue #117: High-level status cards in dashboard API."""

    def setUp(self):
        self.client = TestClient(app.app)

    def test_overview_metrics_never_synced(self):
        """Uninitialized daemon evaluates health_state as never_synced."""
        app.sync_state["last_sync"] = None
        app.sync_state["status"] = "Initializing"
        app.update_overview_metrics()

        om = app.sync_state["overview_metrics"]
        self.assertEqual(om["health_state"], "never_synced")

    def test_overview_metrics_healthy_state(self):
        """Active sync with valid services evaluates health_state as healthy."""
        app.sync_state["last_sync"] = "2026-10-18 10:00:00"
        app.sync_state["status"] = "Active / Synced"
        app.sync_state["docker_connected"] = True
        app.sync_state["safety_guard_tripped"] = False
        app.sync_state["services"] = [
            {"name": "svc1", "status": "Active & Synced"},
            {"name": "svc2", "status": "Active & Synced"},
        ]
        app.sync_state["discovered_services"] = app.sync_state["services"]
        app.update_overview_metrics()

        om = app.sync_state["overview_metrics"]
        self.assertEqual(om["health_state"], "healthy")
        self.assertEqual(om["active_services"], 2)
        self.assertEqual(om["failed_services"], 0)
        self.assertEqual(om["discovered_services"], 2)

    def test_overview_metrics_degraded_on_failed_services_or_disconnected_docker(self):
        """Degraded service states or disconnected Docker evaluates health_state as degraded."""
        app.sync_state["last_sync"] = "2026-10-18 10:00:00"
        app.sync_state["status"] = "Degraded"
        app.sync_state["services"] = [
            {"name": "svc1", "status": "Degraded"},
        ]
        app.update_overview_metrics()
        self.assertEqual(app.sync_state["overview_metrics"]["health_state"], "degraded")

        # Docker disconnected
        app.sync_state["docker_connected"] = False
        app.update_overview_metrics()
        self.assertEqual(app.sync_state["overview_metrics"]["health_state"], "degraded")
        self.assertFalse(app.sync_state["overview_metrics"]["api_connected"])

    def test_api_status_exposes_overview_metrics(self):
        """GET /api/status returns fresh overview_metrics, sync_history, and events."""
        with patch.dict(os.environ, {"DASHBOARD_AUTH_ENABLED": "false"}, clear=False):
            resp = self.client.get("/api/status")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("overview_metrics", data)
            self.assertIn("health_state", data["overview_metrics"])
            self.assertIn("sync_history", data)
            self.assertIn("events", data)
            self.assertIn("alert_status", data)


class TestSyncDurationAndHistoryRingBuffer(unittest.TestCase):
    """Issue #119: Sync duration & run history ring-buffer."""

    def setUp(self):
        self.client = TestClient(app.app)
        app.sync_state["sync_history"].clear()

    def test_history_ring_buffer_bounds(self):
        """History ring-buffer records runs and strictly enforces 20-item bound."""
        for i in range(25):
            app.record_sync_history(
                duration_ms=float(i * 10),
                status="Active / Synced",
                services_count=i,
                summary={"test": i},
            )

        self.assertEqual(len(app.sync_state["sync_history"]), 20)
        # Most recent run should be first
        self.assertEqual(app.sync_state["sync_history"][0]["duration_ms"], 240.0)

    def test_get_api_history_endpoint(self):
        """GET /api/history returns ordered history list respecting limit."""
        app.record_sync_history(duration_ms=120.5, status="Active / Synced", services_count=2)
        app.record_sync_history(duration_ms=85.2, status="Degraded", services_count=1)

        with patch.dict(os.environ, {"DASHBOARD_AUTH_ENABLED": "false"}, clear=False):
            resp = self.client.get("/api/history?limit=1")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(len(data["history"]), 1)
            self.assertEqual(data["history"][0]["status"], "Degraded")
            self.assertEqual(data["total"], 2)


class TestSearchableEventTimeline(unittest.TestCase):
    """Issue #120: Searchable/Filterable Event timeline with redaction."""

    def setUp(self):
        self.client = TestClient(app.app)
        app.sync_state["events"].clear()

    def test_event_recording_and_bounds(self):
        """Events are recorded with ISO time and bounded to 100 entries."""
        for i in range(110):
            app.record_event(
                severity="info",
                event_type="DNS_CREATE",
                service=f"service-{i}.example.com",
                message=f"Created DNS record for service-{i}",
            )

        self.assertEqual(len(app.sync_state["events"]), 100)
        self.assertEqual(app.sync_state["events"][0]["service"], "service-109.example.com")

    def test_event_redaction_guarantee(self):
        """Sensitive tokens and keys inside event messages are automatically redacted."""
        app.record_event(
            severity="error",
            event_type="API_ERROR",
            service="auth-service",
            message="Cloudflare API call with token cf_pat_secret_12345 failed with bearer secret_token_xyz",
        )
        evt = app.sync_state["events"][0]
        self.assertNotIn("secret_12345", evt["message"])
        self.assertIn("[REDACTED]", evt["message"])

    def test_get_api_events_filtering(self):
        """GET /api/events filters by severity, service, and search query."""
        app.record_event("info", "DNS_CREATE", "web.example.com", "Created record")
        app.record_event("warning", "DNS_UPDATE", "api.example.com", "Updated record")
        app.record_event("error", "SYNC_ERROR", "db.example.com", "Database connection lost")

        with patch.dict(os.environ, {"DASHBOARD_AUTH_ENABLED": "false"}, clear=False):
            # 1. Filter by severity
            resp_err = self.client.get("/api/events?severity=error")
            self.assertEqual(resp_err.status_code, 200)
            data = resp_err.json()
            self.assertEqual(len(data["events"]), 1)
            self.assertEqual(data["events"][0]["event_type"], "SYNC_ERROR")

            # 2. Filter by search query
            resp_q = self.client.get("/api/events?q=web.example.com")
            self.assertEqual(resp_q.status_code, 200)
            data_q = resp_q.json()
            self.assertEqual(len(data_q["events"]), 1)
            self.assertEqual(data_q["events"][0]["service"], "web.example.com")


class TestWebhookAlertStatusIndicator(unittest.TestCase):
    """Issue #121: Webhook alert delivery status indicator."""

    def setUp(self):
        self.client = TestClient(app.app)

    def test_dispatcher_status_unconfigured(self):
        """Unconfigured dispatcher reports configured=False and provider=none."""
        disp = NotificationDispatcher(webhook_url=None)
        st = disp.get_status()
        self.assertFalse(st["configured"])
        self.assertEqual(st["provider"], "none")

    def test_dispatcher_status_configured_without_secret_leak(self):
        """Configured dispatcher reports provider without exposing webhook URL secrets."""
        disp = NotificationDispatcher(webhook_url="https://discord.com/api/webhooks/12345/top-secret-token")
        st = disp.get_status()
        self.assertTrue(st["configured"])
        self.assertEqual(st["provider"], "discord")
        self.assertNotIn("top-secret-token", str(st))

    def test_get_api_notifications_status(self):
        """GET /api/notifications/status returns dispatcher delivery state."""
        with patch.dict(os.environ, {"DASHBOARD_AUTH_ENABLED": "false"}, clear=False):
            resp = self.client.get("/api/notifications/status")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("configured", data)
            self.assertIn("provider", data)
            self.assertIn("cooldown_active", data)


class TestDashboardUIDiagnosticsBreakdown(unittest.TestCase):
    """Issue #122: Service diagnostic breakdown in UI."""

    def test_dashboard_templates_contain_diagnostic_and_history_elements(self):
        """Both embedded and companion dashboard templates expose diagnostic stages and history."""
        for path in [
            REPO_ROOT / "src/tunnel_sync/web/static/index.html",
            REPO_ROOT / "cf-tunnel-dashboard/index.html",
        ]:
            content = path.read_text(encoding="utf-8")
            js_content = (path.parent / "dashboard.js").read_text(encoding="utf-8")
            full_dashboard = content + "\n" + js_content

            self.assertIn("history-chart-container", full_dashboard)
            self.assertIn("events-timeline-container", full_dashboard)
            self.assertIn("event-search-input", full_dashboard)
            self.assertIn("event-severity-select", full_dashboard)
            self.assertIn("health-state-text", full_dashboard)
            self.assertIn("safety-guard-status", full_dashboard)
            self.assertIn("LABEL_SYNTAX", full_dashboard)
            self.assertIn("CLOUDFLARE_DNS", full_dashboard)


if __name__ == "__main__":
    unittest.main()
