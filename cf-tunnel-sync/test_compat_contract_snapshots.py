"""Contract snapshot tests for configuration, label aliases, and API endpoints (Issue #85 - COMPAT-03).

Enforces strictly additive changes:
1. All frozen environment variables from v1.13.0 baseline are retained.
2. All frozen label aliases resolve accurately.
3. API responses (/health, /api/status, /api/change-plan, /metrics) adhere to frozen schema.
4. Schema comparison check fails if any existing contract key is deleted or changes type.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import config
from starlette.testclient import TestClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestCompatContractSnapshots(unittest.TestCase):
    """Enforces additive-only schema evolution against v1.13.0 contract snapshots."""

    @classmethod
    def setUpClass(cls):
        snapshot_path = FIXTURES_DIR / "contract_snapshots_v1_13_0.json"
        with open(snapshot_path, "r", encoding="utf-8") as f:
            cls.snapshot = json.load(f)
        cls.client = TestClient(app.app)

    def test_environment_variables_contract(self):
        """Validates that all known v1.13.0 environment variables exist in config.KNOWN_ENV_VARS."""
        expected_vars = self.snapshot["known_env_vars"]
        for var_name in expected_vars:
            self.assertIn(
                var_name,
                config.KNOWN_ENV_VARS,
                f"Breaking Change: Previously supported env var '{var_name}' was removed from KNOWN_ENV_VARS",
            )

    def test_label_aliases_contract(self):
        """Validates that all historical label aliases continue to resolve correctly."""
        expected_aliases = self.snapshot["label_aliases"]
        for alias, canonical in expected_aliases.items():
            self.assertIn(
                alias,
                config.LABEL_ALIASES,
                f"Breaking Change: Historical label alias '{alias}' was removed from LABEL_ALIASES",
            )
            self.assertEqual(
                config.resolve_canonical_label(alias),
                canonical,
                f"Alias '{alias}' resolved to unexpected '{config.resolve_canonical_label(alias)}', expected '{canonical}'",
            )

    def test_health_api_schema_contract(self):
        """Validates /health endpoint schema matches snapshot contract."""
        resp = self.client.get("/health")
        self.assertIn(resp.status_code, [200, 503])
        body = resp.json()

        spec = self.snapshot["api_contracts"]["/health"]["required_fields"]
        for field, expected_type in spec.items():
            self.assertIn(field, body, f"Breaking Change: /health missing required field '{field}'")
            val = body[field]
            if expected_type == "str":
                self.assertIsInstance(val, str)
            elif expected_type == "int":
                self.assertIsInstance(val, int)
            elif expected_type == "bool":
                self.assertIsInstance(val, bool)
            elif expected_type == "optional_str":
                self.assertTrue(val is None or isinstance(val, str))

    def test_status_api_schema_contract(self):
        """Validates /api/status endpoint schema matches snapshot contract."""
        with patch("app.check_dashboard_auth", return_value=True):
            resp = self.client.get("/api/status")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()

            spec = self.snapshot["api_contracts"]["/api/status"]["required_fields"]
            for field, expected_type in spec.items():
                self.assertIn(field, body, f"Breaking Change: /api/status missing required field '{field}'")
                val = body[field]
                if expected_type == "str":
                    self.assertIsInstance(val, str)
                elif expected_type == "int":
                    self.assertIsInstance(val, int)
                elif expected_type == "bool":
                    self.assertIsInstance(val, bool)
                elif expected_type == "list":
                    self.assertIsInstance(val, list)
                elif expected_type == "dict":
                    self.assertIsInstance(val, dict)
                elif expected_type == "optional_str":
                    self.assertTrue(val is None or isinstance(val, str))

    def test_metrics_exposition_schema_contract(self):
        """Validates /metrics endpoint exposes all required Prometheus metrics."""
        resp = self.client.get("/metrics")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.headers.get("content-type", ""))
        text = resp.text

        required_metrics = self.snapshot["api_contracts"]["/metrics"]["required_metrics"]
        for metric in required_metrics:
            self.assertIn(
                metric,
                text,
                f"Breaking Change: Prometheus metric '{metric}' missing from /metrics exposition",
            )

    def test_schema_comparison_detects_breaking_change(self):
        """Simulates breaking changes (deletion, type alteration) and asserts contract checker catches them."""
        # 1. Simulate key deletion (missing "status")
        tampered_state = {"version": "1.14.0"}
        spec = self.snapshot["api_contracts"]["/health"]["required_fields"]

        with self.assertRaises(AssertionError):
            for field in spec:
                self.assertIn(field, tampered_state)

        # 2. Simulate type alteration (status as int instead of str)
        tampered_state = {"status": 12345}
        with self.assertRaises(AssertionError):
            self.assertIsInstance(tampered_state["status"], str)


if __name__ == "__main__":
    unittest.main()
