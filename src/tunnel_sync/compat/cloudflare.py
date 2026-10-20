"""Compatibility entry point; transport has no dependency on the application."""

from tunnel_sync.adapters.cloudflare import CloudflareClient as CloudflareClient
from tunnel_sync.compat.defaults import metrics_registry


def cf_api(endpoint, token, method="GET", data=None, paginate=True, max_retries=3, *, report_retry=None):
    return CloudflareClient(metrics=metrics_registry, report_retry=report_retry).sync_request(
        endpoint, token, method=method, data=data, paginate=paginate, max_retries=max_retries
    )
