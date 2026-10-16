import unittest

import app
import httpx
import respx


class TestCloudflarePaginationAndRateLimit(unittest.TestCase):
    def setUp(self):
        app.sync_state["logs"] = []
        self.base_url = "https://api.cloudflare.com/client/v4"

    @respx.mock
    def test_cf_api_pagination_multi_page(self):
        """Verify cf_api retrieves and aggregates all items across multiple pages."""
        page1 = {
            "result": [{"id": "z1", "name": "a.com"}, {"id": "z2", "name": "b.com"}],
            "result_info": {"page": 1, "per_page": 2, "total_pages": 3, "count": 2, "total_count": 5},
        }
        page2 = {
            "result": [{"id": "z3", "name": "c.com"}, {"id": "z4", "name": "d.com"}],
            "result_info": {"page": 2, "per_page": 2, "total_pages": 3, "count": 2, "total_count": 5},
        }
        page3 = {
            "result": [{"id": "z5", "name": "e.com"}],
            "result_info": {"page": 3, "per_page": 2, "total_pages": 3, "count": 1, "total_count": 5},
        }

        r3 = respx.get(f"{self.base_url}/zones", params={"page": "3"}).mock(
            return_value=httpx.Response(200, json=page3)
        )
        r2 = respx.get(f"{self.base_url}/zones", params={"page": "2"}).mock(
            return_value=httpx.Response(200, json=page2)
        )
        r1 = respx.get(f"{self.base_url}/zones", params={}).mock(return_value=httpx.Response(200, json=page1))

        data = app.cf_api("/zones", "fake-token", method="GET")

        self.assertEqual(len(data["result"]), 5)
        self.assertEqual([item["id"] for item in data["result"]], ["z1", "z2", "z3", "z4", "z5"])
        self.assertTrue(r1.called)
        self.assertTrue(r2.called)
        self.assertTrue(r3.called)

    @respx.mock
    def test_cf_api_pagination_single_page(self):
        """Verify cf_api terminates immediately when total_pages == 1."""
        page1 = {
            "result": [{"id": "tun-1"}],
            "result_info": {"page": 1, "per_page": 50, "total_pages": 1, "count": 1},
        }
        r = respx.get(f"{self.base_url}/accounts/123/cfd_tunnel").mock(return_value=httpx.Response(200, json=page1))

        data = app.cf_api("/accounts/123/cfd_tunnel", "fake-token")
        self.assertEqual(len(data["result"]), 1)
        self.assertEqual(r.call_count, 1)

    @respx.mock
    def test_cf_api_rate_limit_retry_success(self):
        """Verify HTTP 429 triggers backoff retry and succeeds upon next attempt."""
        r = respx.get(f"{self.base_url}/zones").mock(
            side_effect=[
                httpx.Response(
                    429,
                    headers={"Retry-After": "0"},
                    json={"errors": [{"code": 10014, "message": "Rate limit exceeded"}]},
                ),
                httpx.Response(200, json={"result": [{"id": "ok-1"}], "result_info": {"page": 1, "total_pages": 1}}),
            ]
        )

        data = app.cf_api("/zones", "fake-token")

        self.assertEqual(len(data["result"]), 1)
        self.assertEqual(data["result"][0]["id"], "ok-1")
        self.assertEqual(r.call_count, 2)
        self.assertTrue(any("429" in log for log in app.sync_state["logs"]))

    @respx.mock
    def test_cf_api_rate_limit_exhaustion(self):
        """Verify HTTP 429 raises RuntimeError when all retries are exhausted."""
        r = respx.get(f"{self.base_url}/zones").mock(
            return_value=httpx.Response(
                429, headers={"Retry-After": "0"}, json={"errors": [{"code": 10014, "message": "Rate limit exceeded"}]}
            )
        )

        with self.assertRaises(RuntimeError) as ctx:
            app.cf_api("/zones", "fake-token", max_retries=3)

        self.assertIn("Rate limit exceeded", str(ctx.exception))
        self.assertEqual(r.call_count, 3)


if __name__ == "__main__":
    unittest.main()
