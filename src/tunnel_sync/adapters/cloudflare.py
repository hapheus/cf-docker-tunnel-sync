import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

from tunnel_sync.adapters.metrics import PrometheusRegistry
from tunnel_sync.adapters.retry import RetryPolicy

logger = logging.getLogger("cf-tunnel-sync")


class CloudflareClient:
    """Modern asynchronous & synchronous Cloudflare API client backed by HTTPX with exponential retry backoff."""

    def __init__(
        self,
        base_url: str = "https://api.cloudflare.com/client/v4",
        timeout: float = 15.0,
        *,
        retry_policy=None,
        metrics=None,
        report_retry=None,
        environment=None,
    ):
        environment = os.environ if environment is None else environment
        self.metrics = metrics if metrics is not None else PrometheusRegistry()
        self.report_retry = report_retry or logger.warning
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        try:
            max_r = int(environment.get("CLOUDFLARE_MAX_RETRIES", "3"))
        except (ValueError, TypeError):
            max_r = 3
        try:
            base_d = float(environment.get("CLOUDFLARE_RETRY_BASE_DELAY", "0.5"))
        except (ValueError, TypeError):
            base_d = 0.5
        self.retry_policy = retry_policy or RetryPolicy(max_retries=max_r, base_delay=base_d)

    async def async_request(
        self,
        endpoint: str,
        token: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        paginate: bool = True,
        max_retries: Optional[int] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """Asynchronously call Cloudflare API with rate-limiting backoff, 5xx retries, and auto-pagination."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        retries_limit = max_retries if max_retries is not None else self.retry_policy.max_retries

        async def _execute_single(c: httpx.AsyncClient, url: str, payload: Optional[Dict[str, Any]] = None):
            for attempt in range(1, retries_limit + 1):
                try:
                    resp = await c.request(method, url, json=payload, headers=headers)
                    status_bucket = f"{resp.status_code // 100}xx"
                    self.metrics.inc_counter(
                        "cf_tunnel_api_requests_total",
                        1.0,
                        {"method": method.upper(), "status": status_bucket},
                    )

                    if self.retry_policy.is_retryable(resp.status_code) and attempt < retries_limit:
                        retry_after = resp.headers.get("Retry-After")
                        sleep_time = self.retry_policy.get_delay(attempt, retry_after)
                        msg = (
                            f"Cloudflare API status {resp.status_code} on {url}, "
                            f"retrying attempt {attempt + 1}/{retries_limit} in {sleep_time:.2f}s"
                        )
                        logger.warning(msg)
                        self.report_retry(msg)
                        await asyncio.sleep(sleep_time)
                        continue

                    if resp.is_error:
                        self.metrics.record_cloudflare_error(resp.status_code)
                        try:
                            err_json = resp.json()
                            errors = err_json.get("errors", [])
                            if errors:
                                err_text = "; ".join(
                                    f"{err.get('message')} (code: {err.get('code')})" for err in errors
                                )
                                raise RuntimeError(f"Cloudflare API Error ({resp.status_code}): {err_text}") from None
                        except Exception:
                            # Response is not valid JSON or lacks error structure; fall back to raw HTTP error
                            pass
                        raise RuntimeError(f"Cloudflare HTTP {resp.status_code}: {resp.text}") from None

                    return resp.json()
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    if attempt < retries_limit:
                        sleep_time = self.retry_policy.get_delay(attempt)
                        logger.warning(
                            "Cloudflare network exception %s on %s, retrying in %.2fs",
                            type(e).__name__,
                            url,
                            sleep_time,
                        )
                        await asyncio.sleep(sleep_time)
                        continue
                    raise RuntimeError(f"Cloudflare Network Error: {e}") from None

            raise RuntimeError(f"Cloudflare API failed after {retries_limit} retries on {url}")

        # Execute using provided or transient async client
        if client:
            first_resp = await _execute_single(client, f"{self.base_url}{endpoint}", data)
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as local_client:
                first_resp = await _execute_single(local_client, f"{self.base_url}{endpoint}", data)

        if method == "GET" and paginate and isinstance(first_resp, dict):
            result_info = first_resp.get("result_info")
            if isinstance(result_info, dict):
                total_pages = result_info.get("total_pages", 1)
                current_page = result_info.get("page", 1)
                all_results = list(first_resp.get("result", []))

                while current_page < total_pages:
                    current_page += 1
                    delim = "&" if "?" in endpoint else "?"
                    page_endpoint = f"{endpoint}{delim}page={current_page}"
                    if client:
                        next_resp = await _execute_single(client, f"{self.base_url}{page_endpoint}")
                    else:
                        async with httpx.AsyncClient(timeout=self.timeout) as local_client:
                            next_resp = await _execute_single(local_client, f"{self.base_url}{page_endpoint}")
                    if isinstance(next_resp, dict) and isinstance(next_resp.get("result"), list):
                        all_results.extend(next_resp["result"])
                    else:
                        break

                first_resp["result"] = all_results

        return first_resp

    def sync_request(
        self,
        endpoint: str,
        token: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        paginate: bool = True,
        max_retries: Optional[int] = None,
        client: Optional[httpx.Client] = None,
    ) -> Dict[str, Any]:
        """Synchronously call Cloudflare API with rate-limiting backoff, 5xx retries, and auto-pagination."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        retries_limit = max_retries if max_retries is not None else self.retry_policy.max_retries

        def _execute_single(c: httpx.Client, url: str, payload: Optional[Dict[str, Any]] = None):
            for attempt in range(1, retries_limit + 1):
                try:
                    resp = c.request(method, url, json=payload, headers=headers)
                    status_bucket = f"{resp.status_code // 100}xx"
                    self.metrics.inc_counter(
                        "cf_tunnel_api_requests_total",
                        1.0,
                        {"method": method.upper(), "status": status_bucket},
                    )

                    if self.retry_policy.is_retryable(resp.status_code) and attempt < retries_limit:
                        retry_after = resp.headers.get("Retry-After")
                        sleep_time = self.retry_policy.get_delay(attempt, retry_after)
                        msg = (
                            f"Cloudflare API status {resp.status_code} on {url}, "
                            f"retrying attempt {attempt + 1}/{retries_limit} in {sleep_time:.2f}s"
                        )
                        logger.warning(msg)
                        self.report_retry(msg)
                        time.sleep(sleep_time)
                        continue

                    if resp.is_error:
                        self.metrics.record_cloudflare_error(resp.status_code)
                        try:
                            err_json = resp.json()
                            errors = err_json.get("errors", [])
                            if errors:
                                err_text = "; ".join(
                                    f"{err.get('message')} (code: {err.get('code')})" for err in errors
                                )
                                raise RuntimeError(f"Cloudflare API Error ({resp.status_code}): {err_text}") from None
                        except Exception:
                            # Response is not valid JSON or lacks error structure; fall back to raw HTTP error
                            pass
                        raise RuntimeError(f"Cloudflare HTTP {resp.status_code}: {resp.text}") from None

                    return resp.json()
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    if attempt < retries_limit:
                        sleep_time = self.retry_policy.get_delay(attempt)
                        logger.warning(
                            "Cloudflare network exception %s on %s, retrying in %.2fs",
                            type(e).__name__,
                            url,
                            sleep_time,
                        )
                        time.sleep(sleep_time)
                        continue
                    raise RuntimeError(f"Cloudflare Network Error: {e}") from None

            raise RuntimeError(f"Cloudflare API failed after {retries_limit} retries on {url}")

        if client:
            first_resp = _execute_single(client, f"{self.base_url}{endpoint}", data)
        else:
            with httpx.Client(timeout=self.timeout) as local_client:
                first_resp = _execute_single(local_client, f"{self.base_url}{endpoint}", data)

        if method == "GET" and paginate and isinstance(first_resp, dict):
            result_info = first_resp.get("result_info")
            if isinstance(result_info, dict):
                total_pages = result_info.get("total_pages", 1)
                current_page = result_info.get("page", 1)
                all_results = list(first_resp.get("result", []))

                while current_page < total_pages:
                    current_page += 1
                    delim = "&" if "?" in endpoint else "?"
                    page_endpoint = f"{endpoint}{delim}page={current_page}"
                    if client:
                        next_resp = _execute_single(client, f"{self.base_url}{page_endpoint}")
                    else:
                        with httpx.Client(timeout=self.timeout) as local_client:
                            next_resp = _execute_single(local_client, f"{self.base_url}{page_endpoint}")
                    if isinstance(next_resp, dict) and isinstance(next_resp.get("result"), list):
                        all_results.extend(next_resp["result"])
                    else:
                        break

                first_resp["result"] = all_results

        return first_resp


class CloudflareReadAdapter:
    """Read capability only; cannot execute a mutating HTTP method."""

    def __init__(self, request):
        self._request = request

    def read(self, endpoint, token, method="GET"):
        if method != "GET":
            raise ValueError("Cloudflare reader only supports GET")
        return self._request(endpoint, token, method=method)


class CloudflareWriteAdapter:
    def __init__(self, request):
        self._request = request

    def mutate(self, endpoint, token, method, data=None):
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Cloudflare writer requires a mutation method")
        return self._request(endpoint, token, method=method, data=data)
