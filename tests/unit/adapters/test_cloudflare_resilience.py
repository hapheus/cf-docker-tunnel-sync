"""Tests for Cloudflare API failures, rate limiting, and idempotency (SAFE-06 / Issue #106)."""

import unittest
from unittest.mock import patch

import httpx
import respx

from cloudflare import CloudflareClient
from resilience import calculate_backoff_delay, parse_retry_after


class TestCloudflareResilience(unittest.TestCase):
    def setUp(self):
        self.client = CloudflareClient(base_url="https://api.cloudflare.com/client/v4")

    @respx.mock
    def test_cf_api_429_rate_limiting_retries_with_retry_after(self):
        """TC-106-01: HTTP 429 Too Many Requests observes Retry-After header and succeeds on retry."""
        route = respx.get("https://api.cloudflare.com/client/v4/zones")
        route.side_effect = [
            httpx.Response(
                429, headers={"Retry-After": "0.1"}, json={"errors": [{"code": 10000, "message": "rate limited"}]}
            ),
            httpx.Response(200, json={"result": [{"id": "z1", "name": "example.com"}]}),
        ]

        with patch("time.sleep") as mock_sleep:
            res = self.client.sync_request("/zones", token="fake-token")

        self.assertEqual(len(res.get("result", [])), 1)
        self.assertEqual(res["result"][0]["id"], "z1")
        mock_sleep.assert_called_once_with(0.1)

    @respx.mock
    def test_cf_api_500_server_error_exponential_backoff(self):
        """TC-106-02: HTTP 500 Server Error triggers exponential backoff and succeeds on 3rd attempt."""
        route = respx.get("https://api.cloudflare.com/client/v4/zones")
        route.side_effect = [
            httpx.Response(500, json={"errors": [{"code": 500, "message": "internal error"}]}),
            httpx.Response(502, json={"errors": [{"code": 502, "message": "bad gateway"}]}),
            httpx.Response(200, json={"result": [{"id": "z1", "name": "example.com"}]}),
        ]

        with patch("time.sleep") as mock_sleep:
            res = self.client.sync_request("/zones", token="fake-token")

        self.assertEqual(res["result"][0]["id"], "z1")
        self.assertEqual(mock_sleep.call_count, 2)

    @respx.mock
    def test_cf_api_401_unauthorized_fails_fast_without_retries(self):
        """TC-106-03: HTTP 401 Unauthorized fails immediately without retrying."""
        respx.get("https://api.cloudflare.com/client/v4/zones").mock(
            return_value=httpx.Response(401, json={"errors": [{"code": 9109, "message": "Invalid access token"}]})
        )

        with patch("time.sleep") as mock_sleep:
            with self.assertRaises(RuntimeError) as ctx:
                self.client.sync_request("/zones", token="bad-token")

        self.assertIn("401", str(ctx.exception))
        self.assertIn("Invalid access token", str(ctx.exception))
        mock_sleep.assert_not_called()

    @respx.mock
    def test_cf_api_403_forbidden_fails_fast(self):
        """TC-106-04: HTTP 403 Forbidden fails immediately without retrying."""
        respx.get("https://api.cloudflare.com/client/v4/zones").mock(
            return_value=httpx.Response(403, json={"errors": [{"code": 9106, "message": "Missing permissions"}]})
        )

        with patch("time.sleep") as mock_sleep:
            with self.assertRaises(RuntimeError) as ctx:
                self.client.sync_request("/zones", token="token")

        self.assertIn("403", str(ctx.exception))
        mock_sleep.assert_not_called()

    def test_backoff_calculation_and_jitter(self):
        """TC-106-05: Backoff calculation produces exponential delays clamped to max_delay."""
        d1 = calculate_backoff_delay(1, base_delay=1.0, with_jitter=False)
        d2 = calculate_backoff_delay(2, base_delay=1.0, with_jitter=False)
        d3 = calculate_backoff_delay(3, base_delay=1.0, with_jitter=False)
        d_clamped = calculate_backoff_delay(10, base_delay=1.0, max_delay=10.0, with_jitter=False)

        self.assertEqual(d1, 1.0)
        self.assertEqual(d2, 2.0)
        self.assertEqual(d3, 4.0)
        self.assertEqual(d_clamped, 10.0)

    def test_parse_retry_after_bounds(self):
        """TC-106-06: Retry-After parser respects minimum and maximum bounds."""
        self.assertEqual(parse_retry_after("5"), 5.0)
        self.assertEqual(parse_retry_after("0"), 0.1)  # clamped to 0.1s minimum
        self.assertEqual(parse_retry_after("999999", max_delay=60.0), 60.0)  # clamped to 60s max
        self.assertEqual(parse_retry_after(None, default_delay=2.0), 2.0)

    @respx.mock
    def test_client_request_and_sync_alias_parity(self):
        """Unified request() and legacy sync_request() alias behave identically."""
        respx.get("https://api.cloudflare.com/client/v4/zones").mock(
            return_value=httpx.Response(200, json={"result": [{"id": "z1"}]})
        )
        res1 = self.client.request("/zones", token="fake-token")
        res2 = self.client.sync_request("/zones", token="fake-token")
        self.assertEqual(res1, res2)
        self.assertEqual(res1["result"][0]["id"], "z1")
        self.assertFalse(hasattr(self.client, "async_request"), "Dead async_request method must be removed")


if __name__ == "__main__":
    unittest.main()
