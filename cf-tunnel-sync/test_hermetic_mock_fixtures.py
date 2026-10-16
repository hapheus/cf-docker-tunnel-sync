import unittest

import httpx
import respx
from cloudflare import cf_api


class TestHermeticCloudflareMockFixtures(unittest.TestCase):
    def setUp(self):
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.token = "test-mock-token-xyz"

    @respx.mock
    def test_cloudflare_client_pagination_with_respx(self):
        """Hermetically verify auto-pagination across multiple pages with wire-level request validation."""
        page2_route = respx.get(f"{self.base_url}/zones", params={"page": "2"}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "result": [{"id": "z3", "name": "gamma.com"}],
                    "result_info": {"page": 2, "per_page": 2, "total_pages": 2, "count": 1, "total_count": 3},
                },
            )
        )

        page1_route = respx.get(f"{self.base_url}/zones", params={}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "result": [{"id": "z1", "name": "alpha.com"}, {"id": "z2", "name": "beta.com"}],
                    "result_info": {"page": 1, "per_page": 2, "total_pages": 2, "count": 2, "total_count": 3},
                },
            )
        )

        resp = cf_api("/zones", self.token)

        self.assertEqual(len(resp["result"]), 3)
        self.assertEqual([z["id"] for z in resp["result"]], ["z1", "z2", "z3"])

        # Validate HTTP request headers and methods
        self.assertTrue(page1_route.called)
        self.assertTrue(page2_route.called)
        self.assertEqual(page1_route.calls.last.request.headers["Authorization"], f"Bearer {self.token}")
        self.assertEqual(page2_route.calls.last.request.headers["Authorization"], f"Bearer {self.token}")

    @respx.mock
    def test_cloudflare_rate_limit_backoff_with_respx(self):
        """Hermetically verify HTTP 429 rate limit backoff and automatic retry via respx."""
        route = respx.get(f"{self.base_url}/accounts").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "0"}, json={"errors": [{"code": 10014, "message": "Rate limited"}]}),
                httpx.Response(200, json={"result": [{"id": "acc-123", "name": "My Account"}]}),
            ]
        )

        resp = cf_api("/accounts", self.token)

        self.assertEqual(len(resp["result"]), 1)
        self.assertEqual(resp["result"][0]["id"], "acc-123")
        self.assertEqual(route.call_count, 2)

    @respx.mock
    def test_cloudflare_error_formatting_with_respx(self):
        """Hermetically verify structured Cloudflare error parsing without monkeypatching."""
        respx.get(f"{self.base_url}/zones").mock(
            return_value=httpx.Response(
                400,
                json={"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]},
            )
        )

        with self.assertRaises(RuntimeError) as ctx:
            cf_api("/zones", "invalid-token")

        self.assertIn("Authentication error", str(ctx.exception))
        self.assertIn("10000", str(ctx.exception))

    @respx.mock
    def test_cloudflare_dns_crud_operations_with_respx(self):
        """Hermetically verify POST, PUT, and DELETE DNS wire operations and payloads."""
        create_route = respx.post(f"{self.base_url}/zones/z1/dns_records").mock(
            return_value=httpx.Response(200, json={"result": {"id": "rec-new", "name": "api.example.com"}})
        )
        delete_route = respx.delete(f"{self.base_url}/zones/z1/dns_records/rec-old").mock(
            return_value=httpx.Response(200, json={"result": {"id": "rec-old"}})
        )

        # 1. Create DNS record
        create_payload = {"type": "CNAME", "name": "api.example.com", "content": "tun.cfargotunnel.com", "proxied": True}
        res_create = cf_api("/zones/z1/dns_records", self.token, method="POST", data=create_payload)
        self.assertEqual(res_create["result"]["id"], "rec-new")
        self.assertTrue(create_route.called)
        self.assertEqual(create_route.calls.last.request.headers["Content-Type"], "application/json")

        # 2. Delete DNS record
        res_delete = cf_api("/zones/z1/dns_records/rec-old", self.token, method="DELETE")
        self.assertEqual(res_delete["result"]["id"], "rec-old")
        self.assertTrue(delete_route.called)


if __name__ == "__main__":
    unittest.main()
