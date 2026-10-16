import os
import socket
import unittest
from unittest.mock import MagicMock, patch

import app
from fastapi import Response, status


class TestResilientDockerSocket(unittest.TestCase):
    def setUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["docker_connected"] = True
        app.sync_state["logs"] = []

    def test_unix_http_connection_timeout_applied(self):
        """Verify UnixHTTPConnection sets socket timeout properly."""
        with patch("socket.socket") as mock_socket_ctor:
            mock_sock = MagicMock()
            mock_socket_ctor.return_value = mock_sock

            conn = app.UnixHTTPConnection("/fake/docker.sock", timeout=5.0)
            conn.connect()

            mock_socket_ctor.assert_called_once_with(socket.AF_UNIX, socket.SOCK_STREAM)
            mock_sock.settimeout.assert_called_once_with(5.0)
            mock_sock.connect.assert_called_once_with("/fake/docker.sock")

    @patch("os.path.exists", return_value=True)
    @patch("app.UnixHTTPConnection")
    def test_docker_api_timeout_retry_and_degradation(self, mock_conn_cls, mock_exists):
        """Verify that socket timeouts trigger retries and flag docker_connected=False upon exhaustion."""
        mock_conn = MagicMock()
        mock_conn.request.side_effect = socket.timeout("Socket timed out")
        mock_conn_cls.return_value = mock_conn

        with patch("time.sleep") as mock_sleep:
            result = app.docker_api("/containers/json", timeout=2.0, retries=3)

        self.assertEqual(result, [])
        self.assertFalse(app.sync_state["docker_connected"])
        self.assertEqual(mock_conn.request.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertTrue(any("timeout" in log.lower() for log in app.sync_state["logs"]))

    @patch("os.path.exists", return_value=True)
    @patch("app.UnixHTTPConnection")
    def test_docker_api_reconnect_recovery(self, mock_conn_cls, mock_exists):
        """Verify that a transient error recovers on subsequent retry and marks docker_connected=True."""
        app.sync_state["docker_connected"] = False

        failing_conn = MagicMock()
        failing_conn.request.side_effect = ConnectionError("Connection refused")

        success_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'[{"Id": "c1", "State": "running"}]'
        success_conn.getresponse.return_value = mock_resp

        mock_conn_cls.side_effect = [failing_conn, success_conn]

        with patch("time.sleep"):
            result = app.docker_api("/containers/json", timeout=2.0, retries=3)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Id"], "c1")
        self.assertTrue(app.sync_state["docker_connected"])

    @patch("os.path.exists", return_value=False)
    def test_docker_api_socket_missing(self, mock_exists):
        """Verify that a missing socket marks docker_connected=False and returns empty list."""
        result = app.docker_api("/containers/json")
        self.assertEqual(result, [])
        self.assertFalse(app.sync_state["docker_connected"])

    def test_health_endpoint_healthy_state(self):
        """Verify /health returns healthy when docker_connected=True."""
        app.sync_state["docker_connected"] = True
        app.sync_state["status"] = "Active / Synced"

        data = app.health()
        self.assertEqual(data["status"], "healthy")
        self.assertTrue(data["docker_connected"])

    def test_health_endpoint_degraded_state(self):
        """Verify /health reports degraded status when docker_connected=False."""
        app.sync_state["docker_connected"] = False
        app.sync_state["status"] = "Docker connection degraded"

        data = app.health()
        self.assertEqual(data["status"], "degraded")
        self.assertFalse(data["docker_connected"])

    def test_ready_endpoint_status_codes(self):
        """Verify /ready returns 200 when connected and 503 when degraded."""
        app.sync_state["docker_connected"] = True
        resp_ok = Response()
        res_ok = app.ready(resp_ok)
        self.assertEqual(res_ok["status"], "ready")
        self.assertEqual(resp_ok.status_code, 200)

        app.sync_state["docker_connected"] = False
        resp_err = Response()
        res_err = app.ready(resp_err)
        self.assertEqual(res_err["status"], "not ready")
        self.assertEqual(resp_err.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @patch("builtins.open", MagicMock())
    @patch("os.makedirs", MagicMock())
    @patch("app.cf_api")
    @patch("app.docker_api", return_value=[])
    @patch("app.get_docker_containers")
    def test_sync_logic_aborts_on_docker_disconnect(self, mock_get_containers, mock_docker_api, mock_cf_api):
        """Verify run_sync_logic aborts and does not modify Cloudflare when docker is degraded."""
        app.sync_state["docker_connected"] = False
        mock_get_containers.return_value = ([], [])

        with patch.dict(
            os.environ,
            {
                "CLOUDFLARE_API_TOKEN": "fake-token",
                "CLOUDFLARE_ACCOUNT_ID": "fake-acc",
                "CLOUDFLARE_TUNNEL_NAME": "fake-tunnel",
                "DOMAIN_NAME": "example.com",
            },
        ):
            mock_cf_api.return_value = {"result": [{"id": "tun-123", "name": "fake-tunnel"}]}
            app.run_sync_logic()

        self.assertEqual(app.sync_state["status"], "Docker connection degraded")
        self.assertTrue(any("degraded or unreachable" in log for log in app.sync_state["logs"]))


if __name__ == "__main__":
    unittest.main()
