import unittest
from unittest.mock import patch, MagicMock
import urllib.error
import io
import json
import app


class TestCloudflarePaginationAndRateLimit(unittest.TestCase):
    def setUp(self):
        app.sync_state["logs"] = []

    @patch("urllib.request.urlopen")
    def test_cf_api_pagination_multi_page(self, mock_urlopen):
        """Verify cf_api retrieves and aggregates all items across multiple pages."""
        page1 = {
            "result": [{"id": "z1", "name": "a.com"}, {"id": "z2", "name": "b.com"}],
            "result_info": {"page": 1, "per_page": 2, "total_pages": 3, "count": 2, "total_count": 5}
        }
        page2 = {
            "result": [{"id": "z3", "name": "c.com"}, {"id": "z4", "name": "d.com"}],
            "result_info": {"page": 2, "per_page": 2, "total_pages": 3, "count": 2, "total_count": 5}
        }
        page3 = {
            "result": [{"id": "z5", "name": "e.com"}],
            "result_info": {"page": 3, "per_page": 2, "total_pages": 3, "count": 1, "total_count": 5}
        }

        resp1 = MagicMock()
        resp1.read.return_value = json.dumps(page1).encode("utf-8")
        resp1.__enter__.return_value = resp1

        resp2 = MagicMock()
        resp2.read.return_value = json.dumps(page2).encode("utf-8")
        resp2.__enter__.return_value = resp2

        resp3 = MagicMock()
        resp3.read.return_value = json.dumps(page3).encode("utf-8")
        resp3.__enter__.return_value = resp3

        mock_urlopen.side_effect = [resp1, resp2, resp3]

        data = app.cf_api("/zones", "fake-token", method="GET")

        self.assertEqual(len(data["result"]), 5)
        self.assertEqual([item["id"] for item in data["result"]], ["z1", "z2", "z3", "z4", "z5"])
        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("urllib.request.urlopen")
    def test_cf_api_pagination_single_page(self, mock_urlopen):
        """Verify cf_api terminates immediately when total_pages == 1."""
        page1 = {
            "result": [{"id": "tun-1"}],
            "result_info": {"page": 1, "per_page": 50, "total_pages": 1, "count": 1}
        }
        resp1 = MagicMock()
        resp1.read.return_value = json.dumps(page1).encode("utf-8")
        resp1.__enter__.return_value = resp1

        mock_urlopen.return_value = resp1

        data = app.cf_api("/accounts/123/cfd_tunnel", "fake-token")
        self.assertEqual(len(data["result"]), 1)
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_cf_api_rate_limit_retry_success(self, mock_urlopen, mock_sleep):
        """Verify HTTP 429 triggers backoff retry and succeeds upon next attempt."""
        err_fp = io.BytesIO(b'{"errors": [{"code": 10014, "message": "Rate limit exceeded"}]}')
        headers = {"Retry-After": "1"}
        http_429 = urllib.error.HTTPError("https://api.cloudflare.com", 429, "Too Many Requests", headers, err_fp)

        success_page = {
            "result": [{"id": "ok-1"}],
            "result_info": {"page": 1, "total_pages": 1}
        }
        resp_ok = MagicMock()
        resp_ok.read.return_value = json.dumps(success_page).encode("utf-8")
        resp_ok.__enter__.return_value = resp_ok

        mock_urlopen.side_effect = [http_429, resp_ok]

        data = app.cf_api("/zones", "fake-token")

        self.assertEqual(len(data["result"]), 1)
        self.assertEqual(data["result"][0]["id"], "ok-1")
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)
        self.assertTrue(any("429" in log for log in app.sync_state["logs"]))

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_cf_api_rate_limit_exhaustion(self, mock_urlopen, mock_sleep):
        """Verify HTTP 429 raises RuntimeError when all retries are exhausted."""
        def make_429():
            err_fp = io.BytesIO(b'{"errors": [{"code": 10014, "message": "Rate limit exceeded"}]}')
            headers = {"Retry-After": "0"}
            return urllib.error.HTTPError("https://api.cloudflare.com", 429, "Too Many Requests", headers, err_fp)

        mock_urlopen.side_effect = [make_429(), make_429(), make_429()]

        with self.assertRaises(RuntimeError) as ctx:
            app.cf_api("/zones", "fake-token", max_retries=3)

        self.assertIn("Rate limit exceeded", str(ctx.exception))
        self.assertEqual(mock_urlopen.call_count, 3)


if __name__ == "__main__":
    unittest.main()
