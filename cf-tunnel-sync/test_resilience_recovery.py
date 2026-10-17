"""Hermetic tests for deterministic recovery and exponential backoff retry engine (Issue #53 - R06)."""

import unittest
from unittest.mock import MagicMock, patch

import httpx
from cloudflare import CloudflareClient
from resilience import RetryPolicy, calculate_backoff_delay, parse_retry_after


class TestResilienceRecovery(unittest.TestCase):
    def test_calculate_backoff_delay_exponential(self):
        """Verify backoff delays grow exponentially without jitter."""
        d1 = calculate_backoff_delay(1, base_delay=1.0, with_jitter=False)
        d2 = calculate_backoff_delay(2, base_delay=1.0, with_jitter=False)
        d3 = calculate_backoff_delay(3, base_delay=1.0, with_jitter=False)
        d4 = calculate_backoff_delay(4, base_delay=1.0, with_jitter=False)

        self.assertEqual(d1, 1.0)
        self.assertEqual(d2, 2.0)
        self.assertEqual(d3, 4.0)
        self.assertEqual(d4, 8.0)

    def test_calculate_backoff_delay_clamping(self):
        """Verify backoff delay never exceeds max_delay."""
        d = calculate_backoff_delay(10, base_delay=1.0, max_delay=15.0, with_jitter=False)
        self.assertEqual(d, 15.0)

    def test_calculate_backoff_delay_jitter_bounds(self):
        """Verify jitter adds between 0% and 25% extra delay."""
        base = 2.0
        for _ in range(20):
            d = calculate_backoff_delay(2, base_delay=base, with_jitter=True)
            # attempt 2 raw delay is 4.0, with up to 25% jitter -> 4.0 to 5.0
            self.assertGreaterEqual(d, 4.0)
            self.assertLessEqual(d, 5.01)

    def test_parse_retry_after(self):
        """Verify Retry-After header parsing and clamping."""
        self.assertEqual(parse_retry_after("5"), 5.0)
        self.assertEqual(parse_retry_after("2.5"), 2.5)
        self.assertEqual(parse_retry_after("invalid"), 1.0)
        self.assertEqual(parse_retry_after(None, default_delay=3.0), 3.0)
        # Clamped to max_delay 60.0
        self.assertEqual(parse_retry_after("120"), 60.0)

    def test_retry_policy_statuses(self):
        """Verify retryable vs non-retryable HTTP status codes."""
        policy = RetryPolicy()
        # Retryable
        self.assertTrue(policy.is_retryable(429))
        self.assertTrue(policy.is_retryable(500))
        self.assertTrue(policy.is_retryable(502))
        self.assertTrue(policy.is_retryable(503))
        self.assertTrue(policy.is_retryable(504))

        # Non-retryable
        self.assertFalse(policy.is_retryable(200))
        self.assertFalse(policy.is_retryable(400))
        self.assertFalse(policy.is_retryable(401))
        self.assertFalse(policy.is_retryable(403))
        self.assertFalse(policy.is_retryable(404))

    @patch("time.sleep")
    def test_cloudflare_client_retries_429_with_retry_after(self, mock_sleep):
        """Verify client retries 429 rate limits respecting Retry-After header."""
        client = CloudflareClient()
        client.retry_policy.base_delay = 0.01

        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "2"}
        resp_429.is_error = True

        resp_200 = MagicMock(spec=httpx.Response)
        resp_200.status_code = 200
        resp_200.is_error = False
        resp_200.json.return_value = {"success": True, "result": [{"id": "t1"}]}

        mock_http_client = MagicMock(spec=httpx.Client)
        mock_http_client.request.side_effect = [resp_429, resp_200]

        res = client.sync_request("/test", "token", client=mock_http_client)
        self.assertTrue(res["success"])
        self.assertEqual(mock_http_client.request.call_count, 2)
        mock_sleep.assert_called_with(2.0)

    @patch("time.sleep")
    def test_cloudflare_client_retries_503_and_recovers(self, mock_sleep):
        """Verify client retries 503 service unavailable and succeeds on subsequent attempt."""
        client = CloudflareClient()
        client.retry_policy.base_delay = 0.01

        resp_503 = MagicMock(spec=httpx.Response)
        resp_503.status_code = 503
        resp_503.headers = {}
        resp_503.is_error = True

        resp_200 = MagicMock(spec=httpx.Response)
        resp_200.status_code = 200
        resp_200.is_error = False
        resp_200.json.return_value = {"success": True}

        mock_http_client = MagicMock(spec=httpx.Client)
        mock_http_client.request.side_effect = [resp_503, resp_200]

        res = client.sync_request("/test", "token", client=mock_http_client)
        self.assertTrue(res["success"])
        self.assertEqual(mock_http_client.request.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

    @patch("time.sleep")
    def test_cloudflare_client_exhausts_retries(self, mock_sleep):
        """Verify client raises RuntimeError when max retries are exceeded on 500."""
        client = CloudflareClient()
        client.retry_policy.max_retries = 2
        client.retry_policy.base_delay = 0.01

        resp_500 = MagicMock(spec=httpx.Response)
        resp_500.status_code = 500
        resp_500.headers = {}
        resp_500.is_error = True
        resp_500.text = "Internal Server Error"
        resp_500.json.side_effect = Exception("not json")

        mock_http_client = MagicMock(spec=httpx.Client)
        mock_http_client.request.return_value = resp_500

        with self.assertRaises(RuntimeError) as ctx:
            client.sync_request("/test", "token", max_retries=2, client=mock_http_client)

        self.assertIn("Cloudflare HTTP 500", str(ctx.exception))
        self.assertEqual(mock_http_client.request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
