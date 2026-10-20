"""Isolated contracts for read capabilities."""

import pytest

from tunnel_sync.adapters.cloudflare import CloudflareReadAdapter


def test_preview_read_capability_rejects_mutation():
    reader = CloudflareReadAdapter(lambda *args, **kwargs: pytest.fail("No transport call expected"))
    with pytest.raises(ValueError, match="GET"):
        reader.read("/zones", "dummy", method="POST")
