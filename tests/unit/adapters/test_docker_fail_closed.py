import os
import socket
import unittest
from unittest.mock import MagicMock, patch

import app


class TestDockerFailClosed(unittest.TestCase):
    """Hermetic unit tests for Issue #40: Fail-closed Docker container discovery."""

    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["docker_connected"] = True
        app.sync_state["logs"] = []
        if "_last_ingress" in app.sync_state:
            del app.sync_state["_last_ingress"]

    def tearDown(self):
        app.sync_state["docker_connected"] = True

    @patch("os.path.exists", return_value=True)
    @patch("app.UnixHTTPConnection")
    def test_tc_40_01_docker_daemon_error_500(self, mock_unix_conn, mock_exists):
        """TC-40-01: HTTP 500 Internal Server Error raises DockerAPIError and fails closed."""
        mock_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.read.return_value = b'{"message": "daemon internal error"}'
        mock_conn.getresponse.return_value = mock_resp
        mock_unix_conn.return_value = mock_conn

        with self.assertRaises(app.DockerAPIError) as ctx:
            app.docker_api("/containers/json?all=true", retries=1)
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertFalse(app.sync_state["docker_connected"])

    @patch("os.path.exists", return_value=True)
    @patch("app.UnixHTTPConnection")
    def test_tc_40_02_docker_daemon_permission_denied_403(self, mock_unix_conn, mock_exists):
        """TC-40-02: HTTP 403 Forbidden raises DockerAPIError and fails closed."""
        mock_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 403
        mock_resp.read.return_value = b'{"message": "permission denied"}'
        mock_conn.getresponse.return_value = mock_resp
        mock_unix_conn.return_value = mock_conn

        with self.assertRaises(app.DockerAPIError) as ctx:
            app.docker_api("/containers/json?all=true", retries=1)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertFalse(app.sync_state["docker_connected"])

    @patch("os.path.exists", return_value=True)
    @patch("app.UnixHTTPConnection")
    def test_tc_40_03_docker_daemon_not_found_404(self, mock_unix_conn, mock_exists):
        """TC-40-03: HTTP 404 Not Found raises DockerAPIError and fails closed."""
        mock_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_resp.read.return_value = b'{"message": "page not found"}'
        mock_conn.getresponse.return_value = mock_resp
        mock_unix_conn.return_value = mock_conn

        with self.assertRaises(app.DockerAPIError) as ctx:
            app.docker_api("/containers/json?all=true", retries=1)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertFalse(app.sync_state["docker_connected"])

    @patch("os.path.exists", return_value=True)
    @patch("app.UnixHTTPConnection")
    def test_tc_40_04_docker_daemon_gateway_error_502_503(self, mock_unix_conn, mock_exists):
        """TC-40-04: HTTP 502/503 Bad Gateway/Unavailable raises DockerAPIError."""
        for code in (502, 503):
            mock_conn = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status = code
            mock_resp.read.return_value = b"<html>502 Bad Gateway</html>"
            mock_conn.getresponse.return_value = mock_resp
            mock_unix_conn.return_value = mock_conn

            with self.assertRaises(app.DockerAPIError) as ctx:
                app.docker_api("/containers/json?all=true", retries=1)
            self.assertEqual(ctx.exception.status_code, code)
            self.assertFalse(app.sync_state["docker_connected"])

    @patch("os.path.exists", return_value=True)
    @patch("app.UnixHTTPConnection")
    def test_tc_40_05_corrupted_non_json_payload(self, mock_unix_conn, mock_exists):
        """TC-40-05: HTTP 200 with non-JSON body raises DockerAPIError."""
        mock_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"<html>Not JSON at all</html>"
        mock_conn.getresponse.return_value = mock_resp
        mock_unix_conn.return_value = mock_conn

        with self.assertRaises(app.DockerAPIError):
            app.docker_api("/containers/json?all=true", retries=1)
        self.assertFalse(app.sync_state["docker_connected"])

    @patch("os.path.exists", return_value=True)
    @patch("app.UnixHTTPConnection")
    def test_tc_40_06_daemon_timeout_socket_disconnect(self, mock_unix_conn, mock_exists):
        """TC-40-06: Socket timeout marks degraded and fails closed."""
        mock_conn = MagicMock()
        mock_conn.getresponse.side_effect = socket.timeout("Read timed out")
        mock_unix_conn.return_value = mock_conn

        with patch("time.sleep"):
            result = app.docker_api("/containers/json?all=true", retries=2)
        self.assertEqual(result, [])
        self.assertFalse(app.sync_state["docker_connected"])

    @patch("app.docker_api")
    def test_get_docker_containers_handles_docker_api_error(self, mock_docker_api):
        """Verify get_docker_containers catches DockerAPIError and fails closed."""
        mock_docker_api.side_effect = app.DockerAPIError("Daemon down", status_code=500)
        app.sync_state["docker_connected"] = True

        services, all_containers = app.get_docker_containers()
        self.assertEqual(services, [])
        self.assertEqual(all_containers, [])
        self.assertFalse(app.sync_state["docker_connected"])

    @patch("app.docker_api")
    def test_get_docker_containers_handles_non_list_response(self, mock_docker_api):
        """Verify get_docker_containers fails closed if docker_api returns a non-list."""
        mock_docker_api.return_value = {"message": "unexpected error"}
        app.sync_state["docker_connected"] = True

        services, all_containers = app.get_docker_containers()
        self.assertEqual(services, [])
        self.assertEqual(all_containers, [])
        self.assertFalse(app.sync_state["docker_connected"])

    @patch("os.makedirs", MagicMock())
    @patch("app.cf_api")
    @patch("app.docker_api")
    def test_tc_40_fail_closed_zero_writes_to_cloudflare_on_500(self, mock_docker_api, mock_cf_api):
        """TC-40-01 end-to-end: HTTP 500 error prevents all Cloudflare mutations (0 writes / 0 deletes)."""
        mock_docker_api.side_effect = app.DockerAPIError("Docker HTTP 500", status_code=500)
        cf_calls = []

        def tracked_cf_api(endpoint, token, method="GET", data=None):
            cf_calls.append({"endpoint": endpoint, "method": method, "data": data})
            if "zones" in endpoint:
                return {"result": [{"id": "zone-123", "name": "example.com", "account": {"id": "acc-123"}}]}
            if "accounts" in endpoint:
                return {"result": [{"id": "acc-123"}]}
            if "cfd_tunnel" in endpoint:
                if "/token" in endpoint:
                    return {"result": "fake-token"}
                return {"result": [{"id": "tun-123", "name": "fake-tunnel"}]}
            return {"result": []}

        mock_cf_api.side_effect = tracked_cf_api

        with (
            patch.dict(
                os.environ,
                {
                    "CLOUDFLARE_API_TOKEN": "secret-token",
                    "CLOUDFLARE_TUNNEL_NAME": "fake-tunnel",
                    "DOMAIN_NAME": "example.com",
                },
            ),
            patch("builtins.open", MagicMock()),
        ):
            app.run_sync_logic()

        # Verify discovery failed closed
        self.assertFalse(app.sync_state["docker_connected"])
        self.assertEqual(app.sync_state["status"], "Docker connection degraded")

        # Crucial check: 0 writes (PUT, POST) and 0 deletes (DELETE) to Cloudflare
        mutations = [c for c in cf_calls if c["method"] in ("PUT", "POST", "DELETE")]
        self.assertEqual(len(mutations), 0, f"Expected 0 mutations to Cloudflare, got: {mutations}")

    @patch("os.makedirs", MagicMock())
    @patch("app.cf_api")
    @patch("app.docker_api")
    def test_tc_40_fail_closed_zero_writes_to_cloudflare_on_invalid_json(self, mock_docker_api, mock_cf_api):
        """TC-40-05 end-to-end: Corrupt response prevents Cloudflare mutations."""
        mock_docker_api.side_effect = app.DockerAPIError("Docker returned non-JSON")
        cf_calls = []

        def tracked_cf_api(endpoint, token, method="GET", data=None):
            cf_calls.append({"endpoint": endpoint, "method": method, "data": data})
            if "zones" in endpoint:
                return {"result": [{"id": "zone-123", "name": "example.com", "account": {"id": "acc-123"}}]}
            if "accounts" in endpoint:
                return {"result": [{"id": "acc-123"}]}
            if "cfd_tunnel" in endpoint:
                if "/token" in endpoint:
                    return {"result": "fake-token"}
                return {"result": [{"id": "tun-123", "name": "fake-tunnel"}]}
            return {"result": []}

        mock_cf_api.side_effect = tracked_cf_api

        with (
            patch.dict(
                os.environ,
                {
                    "CLOUDFLARE_API_TOKEN": "secret-token",
                    "CLOUDFLARE_TUNNEL_NAME": "fake-tunnel",
                    "DOMAIN_NAME": "example.com",
                },
            ),
            patch("builtins.open", MagicMock()),
        ):
            app.run_sync_logic()

        self.assertFalse(app.sync_state["docker_connected"])
        self.assertEqual(app.sync_state["status"], "Docker connection degraded")
        mutations = [c for c in cf_calls if c["method"] in ("PUT", "POST", "DELETE")]
        self.assertEqual(len(mutations), 0)

    @patch("app.cf_api")
    @patch("app.docker_api")
    def test_tc_40_07_legitimate_empty_container_list(self, mock_docker_api, mock_cf_api):
        """TC-40-07: HTTP 200 with empty list [] is treated as valid discovery (not an error)."""
        mock_docker_api.return_value = []
        app.sync_state["docker_connected"] = True

        services, all_containers = app.get_docker_containers()
        self.assertEqual(services, [])
        self.assertEqual(all_containers, [])
        self.assertTrue(app.sync_state["docker_connected"])


if __name__ == "__main__":
    unittest.main()
