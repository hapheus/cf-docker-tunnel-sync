import unittest
from unittest.mock import patch
import os
import app
from fastapi.security import HTTPBasicCredentials
from fastapi import HTTPException


class TestDashboardAuthenticationAndSingleContainer(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Active / Synced"
        app.sync_state["docker_connected"] = True
        app.sync_state["logs"] = []

    def test_auth_disabled_by_default_when_no_credentials_set(self):
        """Verify that dashboard access succeeds without credentials when no auth is configured."""
        with patch.dict(os.environ, {}, clear=True):
            # No DASHBOARD_USERNAME or BASIC_AUTH_USERNAME configured
            auth_ok = app.check_dashboard_auth(None)
            self.assertTrue(auth_ok)

            resp = app.get_dashboard(authenticated=True)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("Cloudflare", resp.body.decode("utf-8"))

    def test_auth_enabled_rejects_missing_credentials(self):
        """Verify that 401 Unauthorized is raised when credentials are missing and auth is configured."""
        with patch.dict(os.environ, {
            "BASIC_AUTH_USERNAME": "admin",
            "BASIC_AUTH_PASSWORD": "secretpassword"
        }):
            with self.assertRaises(HTTPException) as ctx:
                app.check_dashboard_auth(None)

            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("WWW-Authenticate", ctx.exception.headers)

    def test_auth_enabled_rejects_invalid_credentials(self):
        """Verify that 401 Unauthorized is raised on incorrect credentials."""
        with patch.dict(os.environ, {
            "DASHBOARD_USERNAME": "admin",
            "DASHBOARD_PASSWORD": "correctpassword"
        }):
            bad_creds = HTTPBasicCredentials(username="admin", password="wrongpassword")
            with self.assertRaises(HTTPException) as ctx:
                app.check_dashboard_auth(bad_creds)

            self.assertEqual(ctx.exception.status_code, 401)

    def test_auth_enabled_accepts_valid_credentials(self):
        """Verify that valid credentials authenticate successfully."""
        with patch.dict(os.environ, {
            "DASHBOARD_USERNAME": "admin",
            "DASHBOARD_PASSWORD": "supersecretpassword"
        }):
            valid_creds = HTTPBasicCredentials(username="admin", password="supersecretpassword")
            auth_ok = app.check_dashboard_auth(valid_creds)
            self.assertTrue(auth_ok)

    def test_auth_disabled_via_explicit_toggle(self):
        """Verify DASHBOARD_AUTH_ENABLED=false allows access even if credentials exist in environment."""
        with patch.dict(os.environ, {
            "DASHBOARD_AUTH_ENABLED": "false",
            "BASIC_AUTH_USERNAME": "admin",
            "BASIC_AUTH_PASSWORD": "password123"
        }):
            auth_ok = app.check_dashboard_auth(None)
            self.assertTrue(auth_ok)

    def test_health_endpoints_remain_unauthenticated(self):
        """Verify /health and /ready never require authentication even with auth enabled."""
        with patch.dict(os.environ, {
            "DASHBOARD_USERNAME": "admin",
            "DASHBOARD_PASSWORD": "password123"
        }):
            # health and ready take no credentials parameter and must return 200
            h = app.health()
            self.assertEqual(h["status"], "healthy")

            r = app.ready()
            self.assertEqual(r["status"], "ready")


if __name__ == "__main__":
    unittest.main()
