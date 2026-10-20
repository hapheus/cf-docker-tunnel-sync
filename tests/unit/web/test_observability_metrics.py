"""Hermetic tests for structured JSON logging and Prometheus metrics endpoint (Issue #55 - R08)."""

import json
import logging
import unittest

from starlette.testclient import TestClient

import app
from app import JsonLogFormatter
from metrics import PrometheusRegistry, metrics_registry


class TestObservabilityMetrics(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)

    def test_json_log_formatter_output(self):
        """Verify JsonLogFormatter produces valid single-line JSON with expected schema."""
        formatter = JsonLogFormatter()
        record = logging.LogRecord(
            name="cf-tunnel-sync.test",
            level=logging.WARNING,
            pathname="test_path.py",
            lineno=42,
            msg="Discovery completed with %d services",
            args=(5,),
            exc_info=None,
        )

        formatted = formatter.format(record)
        self.assertNotIn("\n", formatted.strip())

        parsed = json.loads(formatted)
        self.assertEqual(parsed["level"], "WARNING")
        self.assertEqual(parsed["logger"], "cf-tunnel-sync.test")
        self.assertEqual(parsed["message"], "Discovery completed with 5 services")
        self.assertEqual(parsed["module"], "test_path")
        self.assertEqual(parsed["line"], 42)
        self.assertIn("timestamp", parsed)

    def test_prometheus_exposition_format(self):
        """Verify custom registry produces valid Prometheus text exposition lines."""
        registry = PrometheusRegistry()
        registry.record_sync_run(duration=1.23, status="success", discovered_count=4, safety_tripped=False)

        exposition = registry.generate_exposition()

        self.assertIn("# HELP cf_tunnel_sync_runs_total", exposition)
        self.assertIn("# TYPE cf_tunnel_sync_runs_total counter", exposition)
        self.assertIn('cf_tunnel_sync_runs_total{status="success"} 1.0', exposition)

        self.assertIn("# HELP cf_tunnel_sync_duration_seconds", exposition)
        self.assertIn("# TYPE cf_tunnel_sync_duration_seconds gauge", exposition)
        self.assertIn("cf_tunnel_sync_duration_seconds 1.23", exposition)

        self.assertIn("# HELP cf_tunnel_services_discovered", exposition)
        self.assertIn("cf_tunnel_services_discovered 4.0", exposition)

        self.assertIn("# HELP cf_tunnel_safety_guard_tripped", exposition)
        self.assertIn("cf_tunnel_safety_guard_tripped 0.0", exposition)

    def test_get_metrics_endpoint(self):
        """Verify GET /metrics HTTP endpoint responds with Prometheus exposition text."""
        # Record a test run in global registry
        metrics_registry.record_sync_run(duration=0.45, status="success", discovered_count=3, safety_tripped=False)
        metrics_registry.inc_counter("cf_tunnel_api_requests_total", 1.0, {"method": "GET", "status": "2xx"})

        resp = self.client.get("/metrics")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.headers["content-type"])

        body = resp.text
        self.assertIn("cf_tunnel_sync_runs_total", body)
        self.assertIn("cf_tunnel_sync_duration_seconds", body)
        self.assertIn("cf_tunnel_services_discovered", body)
        self.assertIn("cf_tunnel_safety_guard_tripped", body)
        self.assertIn('cf_tunnel_api_requests_total{method="GET",status="2xx"}', body)


if __name__ == "__main__":
    unittest.main()
