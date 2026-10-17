import os
import unittest
from unittest.mock import patch

import app
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials
from starlette.testclient import TestClient


class TestDashboardAuthenticationAndFailClosed(unittest.TestCase):
    def setUp(self):
        # Reset sync state logs before each test
        app.sync_state["logs"].clear()

    # --- TC-42-01 ---
    def test_tc_42_01_auth_enabled_with_empty_credentials_rejects_unauthenticated(self):
        """TC-42-01: When DASHBOARD_AUTH_ENABLED=true and credentials are empty, unauthenticated requests are rejected with 401 (Fail-Closed)."""
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "true",
                "DASHBOARD_USERNAME": "",
                "DASHBOARD_PASSWORD": "",
                "BASIC_AUTH_USERNAME": "",
                "BASIC_AUTH_PASSWORD": "",
            },
            clear=True,
        ):
            with self.assertRaises(HTTPException) as ctx:
                app.check_dashboard_auth(None)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("WWW-Authenticate", ctx.exception.headers)
            self.assertIn("Cloudflare Tunnel Sync Dashboard", ctx.exception.headers["WWW-Authenticate"])

    # --- TC-42-02 ---
    def test_tc_42_02_auth_enabled_with_missing_credentials_rejects_any_credentials(self):
        """TC-42-02: When DASHBOARD_AUTH_ENABLED=true and credentials are missing/unconfigured, any supplied credentials are rejected with 401 (Fail-Closed)."""
        with patch.dict(
            os.environ,
            {"DASHBOARD_AUTH_ENABLED": "true"},
            clear=True,
        ):
            creds = HTTPBasicCredentials(username="admin", password="anypassword")
            with self.assertRaises(HTTPException) as ctx:
                app.check_dashboard_auth(creds)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("WWW-Authenticate", ctx.exception.headers)

    # --- TC-42-03 ---
    def test_tc_42_03_auth_enabled_accepts_valid_credentials(self):
        """TC-42-03: When DASHBOARD_AUTH_ENABLED=true and credentials are configured, valid credentials succeed."""
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "true",
                "DASHBOARD_USERNAME": "admin",
                "DASHBOARD_PASSWORD": "s3cr3t_password",
            },
            clear=True,
        ):
            creds = HTTPBasicCredentials(username="admin", password="s3cr3t_password")
            auth_ok = app.check_dashboard_auth(creds)
            self.assertTrue(auth_ok)

    # --- TC-42-04 ---
    def test_tc_42_04_auth_enabled_rejects_invalid_password_and_invalid_user(self):
        """TC-42-04: When DASHBOARD_AUTH_ENABLED=true, invalid password or invalid username results in 401."""
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "true",
                "DASHBOARD_USERNAME": "admin",
                "DASHBOARD_PASSWORD": "s3cr3t_password",
            },
            clear=True,
        ):
            # Wrong password
            creds_wrong_pwd = HTTPBasicCredentials(username="admin", password="wrongpassword")
            with self.assertRaises(HTTPException) as ctx1:
                app.check_dashboard_auth(creds_wrong_pwd)
            self.assertEqual(ctx1.exception.status_code, 401)
            self.assertIn("WWW-Authenticate", ctx1.exception.headers)

            # Wrong username
            creds_wrong_user = HTTPBasicCredentials(username="wronguser", password="s3cr3t_password")
            with self.assertRaises(HTTPException) as ctx2:
                app.check_dashboard_auth(creds_wrong_user)
            self.assertEqual(ctx2.exception.status_code, 401)
            self.assertIn("WWW-Authenticate", ctx2.exception.headers)

    # --- TC-42-05 ---
    def test_tc_42_05_auth_enabled_with_configured_credentials_rejects_missing_credentials(self):
        """TC-42-05: When DASHBOARD_AUTH_ENABLED=true and credentials configured, unauthenticated requests raise 401."""
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "true",
                "DASHBOARD_USERNAME": "admin",
                "DASHBOARD_PASSWORD": "s3cr3t_password",
            },
            clear=True,
        ):
            with self.assertRaises(HTTPException) as ctx:
                app.check_dashboard_auth(None)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("WWW-Authenticate", ctx.exception.headers)

    # --- TC-42-06 ---
    def test_tc_42_06_auth_disabled_allows_unauthenticated_access_without_credentials(self):
        """TC-42-06: When DASHBOARD_AUTH_ENABLED=false, access succeeds without credentials."""
        with patch.dict(
            os.environ,
            {"DASHBOARD_AUTH_ENABLED": "false"},
            clear=True,
        ):
            auth_ok = app.check_dashboard_auth(None)
            self.assertTrue(auth_ok)

    # --- TC-42-07 ---
    def test_tc_42_07_auth_disabled_allows_unauthenticated_access_even_with_credentials(self):
        """TC-42-07: Setting DASHBOARD_AUTH_ENABLED=false permits access even if credentials exist in environment."""
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "false",
                "DASHBOARD_USERNAME": "admin",
                "DASHBOARD_PASSWORD": "s3cr3t_password",
            },
            clear=True,
        ):
            auth_ok = app.check_dashboard_auth(None)
            self.assertTrue(auth_ok)

    # --- TC-42-08 ---
    def test_tc_42_08_legacy_aliases_basic_auth_username_and_password(self):
        """TC-42-08: Legacy env aliases BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD continue to function."""
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "true",
                "BASIC_AUTH_USERNAME": "legacy_admin",
                "BASIC_AUTH_PASSWORD": "legacy_secret_password",
            },
            clear=True,
        ):
            # Valid legacy credentials succeed
            valid_creds = HTTPBasicCredentials(username="legacy_admin", password="legacy_secret_password")
            self.assertTrue(app.check_dashboard_auth(valid_creds))

            # Invalid legacy credentials fail
            invalid_creds = HTTPBasicCredentials(username="legacy_admin", password="bad_password")
            with self.assertRaises(HTTPException) as ctx:
                app.check_dashboard_auth(invalid_creds)
            self.assertEqual(ctx.exception.status_code, 401)

    # --- TC-42-09 ---
    def test_tc_42_09_health_and_ready_endpoints_remain_unauthenticated(self):
        """TC-42-09: Health and ready endpoints do not require auth regardless of auth configuration."""
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "true",
                "DASHBOARD_USERNAME": "admin",
                "DASHBOARD_PASSWORD": "s3cr3t_password",
            },
            clear=True,
        ):
            h = app.health()
            self.assertEqual(h["status"], "healthy")

            r = app.ready()
            self.assertIn(r["status"], ("ready", "not ready"))

    # --- Default behavior when DASHBOARD_AUTH_ENABLED is unset ---
    def test_default_auth_disabled_when_no_credentials_set(self):
        """Verify dashboard access succeeds when DASHBOARD_AUTH_ENABLED is unset and no credentials exist."""
        with patch.dict(os.environ, {}, clear=True):
            auth_ok = app.check_dashboard_auth(None)
            self.assertTrue(auth_ok)

    def test_implicit_auth_enabled_when_credentials_set_without_auth_flag(self):
        """When credentials are provided but DASHBOARD_AUTH_ENABLED is unset, auth is enforced."""
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_USERNAME": "admin",
                "DASHBOARD_PASSWORD": "s3cr3t_password",
            },
            clear=True,
        ):
            # Missing credentials -> 401
            with self.assertRaises(HTTPException) as ctx:
                app.check_dashboard_auth(None)
            self.assertEqual(ctx.exception.status_code, 401)

            # Valid credentials -> True
            creds = HTTPBasicCredentials(username="admin", password="s3cr3t_password")
            self.assertTrue(app.check_dashboard_auth(creds))


class TestDashboardHTTPRoutesFailClosed(unittest.TestCase):
    """Hermetic HTTP endpoint integration tests via FastAPI TestClient."""

    def setUp(self):
        app.sync_state["logs"].clear()
        self.client = TestClient(app.app)

    def test_http_protected_routes_fail_closed_when_auth_enabled_with_empty_credentials(self):
        """HTTP protected endpoints return 401 with WWW-Authenticate header when auth enabled but credentials empty."""
        with patch.dict(
            os.environ,
            {"DASHBOARD_AUTH_ENABLED": "true"},
            clear=True,
        ):
            for path in ["/", "/dashboard", "/api/status"]:
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, 401, f"Expected 401 on {path}, got {resp.status_code}")
                self.assertIn("WWW-Authenticate", resp.headers)
                self.assertIn('realm="Cloudflare Tunnel Sync Dashboard"', resp.headers["WWW-Authenticate"])

            resp_sync = self.client.post("/api/sync")
            self.assertEqual(resp_sync.status_code, 401)
            self.assertIn("WWW-Authenticate", resp_sync.headers)

            # Health endpoints must still succeed with 200
            self.assertEqual(self.client.get("/health").status_code, 200)
            self.assertEqual(self.client.get("/healthz").status_code, 200)
            self.assertEqual(self.client.get("/ready").status_code, 200)

    def test_http_protected_routes_succeed_with_valid_credentials(self):
        """HTTP protected endpoints return 200 when valid Basic Auth credentials are supplied."""
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "true",
                "DASHBOARD_USERNAME": "admin",
                "DASHBOARD_PASSWORD": "secret_password",
            },
            clear=True,
        ):
            auth = ("admin", "secret_password")
            resp_root = self.client.get("/", auth=auth)
            self.assertEqual(resp_root.status_code, 200)

            resp_status = self.client.get("/api/status", auth=auth)
            self.assertEqual(resp_status.status_code, 200)

            # Invalid credentials return 401
            resp_bad = self.client.get("/", auth=("admin", "wrong_password"))
            self.assertEqual(resp_bad.status_code, 401)
            self.assertIn("WWW-Authenticate", resp_bad.headers)

    def test_http_open_routes_when_auth_explicitly_disabled(self):
        """HTTP endpoints return 200 without authentication when DASHBOARD_AUTH_ENABLED=false."""
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "false",
                "DASHBOARD_USERNAME": "admin",
                "DASHBOARD_PASSWORD": "secret_password",
            },
            clear=True,
        ):
            self.assertEqual(self.client.get("/").status_code, 200)
            self.assertEqual(self.client.get("/api/status").status_code, 200)
            self.assertEqual(self.client.get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
