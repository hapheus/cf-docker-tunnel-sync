import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("cf-tunnel-sync")


class CloudflareClient:
    """Modern asynchronous & synchronous Cloudflare API client backed by HTTPX."""

    def __init__(self, base_url: str = "https://api.cloudflare.com/client/v4", timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def async_request(
        self,
        endpoint: str,
        token: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        paginate: bool = True,
        max_retries: int = 3,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """Asynchronously call Cloudflare API with rate-limiting backoff and auto-pagination."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async def _execute_single(c: httpx.AsyncClient, url: str, payload: Optional[Dict[str, Any]] = None):
            for attempt in range(1, max_retries + 1):
                try:
                    resp = await c.request(method, url, json=payload, headers=headers)
                    if resp.status_code == 429 and attempt < max_retries:
                        retry_after = resp.headers.get("Retry-After")
                        sleep_time = (
                            float(retry_after)
                            if retry_after and retry_after.isdigit()
                            else (0.2 * (2 ** (attempt - 1)))
                        )
                        msg = f"Cloudflare rate limit (429) on {url}, retrying in {sleep_time:.1f}s"
                        logger.warning(msg)
                        try:
                            import app

                            app.add_log(msg)
                        except Exception:
                            pass
                        await asyncio.sleep(sleep_time)
                        continue

                    if resp.is_error:
                        try:
                            err_json = resp.json()
                            errors = err_json.get("errors", [])
                            if errors:
                                err_text = "; ".join(
                                    f"{err.get('message')} (code: {err.get('code')})" for err in errors
                                )
                                raise RuntimeError(f"Cloudflare API Error ({resp.status_code}): {err_text}") from None
                        except (json.JSONDecodeError, AttributeError):
                            pass
                        raise RuntimeError(f"Cloudflare HTTP {resp.status_code}: {resp.text}") from None

                    return resp.json()
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    if attempt < max_retries:
                        await asyncio.sleep(0.2 * (2 ** (attempt - 1)))
                        continue
                    raise RuntimeError(f"Cloudflare Network Error: {e}") from None

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
        max_retries: int = 3,
        client: Optional[httpx.Client] = None,
    ) -> Dict[str, Any]:
        """Synchronously call Cloudflare API with rate-limiting backoff and auto-pagination."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        def _execute_single(c: httpx.Client, url: str, payload: Optional[Dict[str, Any]] = None):
            for attempt in range(1, max_retries + 1):
                try:
                    resp = c.request(method, url, json=payload, headers=headers)
                    if resp.status_code == 429 and attempt < max_retries:
                        retry_after = resp.headers.get("Retry-After")
                        sleep_time = (
                            float(retry_after)
                            if retry_after and retry_after.isdigit()
                            else (0.2 * (2 ** (attempt - 1)))
                        )
                        msg = f"Cloudflare rate limit (429) on {url}, retrying in {sleep_time:.1f}s"
                        logger.warning(msg)
                        try:
                            import app

                            app.add_log(msg)
                        except Exception:
                            pass
                        time.sleep(sleep_time)
                        continue

                    if resp.is_error:
                        try:
                            err_json = resp.json()
                            errors = err_json.get("errors", [])
                            if errors:
                                err_text = "; ".join(
                                    f"{err.get('message')} (code: {err.get('code')})" for err in errors
                                )
                                raise RuntimeError(f"Cloudflare API Error ({resp.status_code}): {err_text}") from None
                        except (json.JSONDecodeError, AttributeError):
                            pass
                        raise RuntimeError(f"Cloudflare HTTP {resp.status_code}: {resp.text}") from None

                    return resp.json()
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    if attempt < max_retries:
                        time.sleep(0.2 * (2 ** (attempt - 1)))
                        continue
                    raise RuntimeError(f"Cloudflare Network Error: {e}") from None

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


# Global default client instance
default_cf_client = CloudflareClient()


def cf_api(
    endpoint: str,
    token: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    paginate: bool = True,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Compatibility helper proxying to default_cf_client.sync_request."""
    return default_cf_client.sync_request(
        endpoint=endpoint,
        token=token,
        method=method,
        data=data,
        paginate=paginate,
        max_retries=max_retries,
    )
