"""Safety contracts independent of production credentials and Docker."""

import os
from unittest.mock import Mock, patch

import pytest

import app
from reconcile import OwnershipStatus, OwnershipTagging


@pytest.mark.parametrize("metadata", [{}, {"comment": None}, {"comment": ""}, {"comment": "  "}])
@pytest.mark.parametrize("active", [True, False])
def test_ownership_requires_explicit_tag(metadata, active):
    record = {"type": "CNAME", "content": "tunnel.cfargotunnel.com", **metadata}
    status = OwnershipTagging(tunnel_name="test").parse_status(record, record["content"], active)
    assert status == (OwnershipStatus.ADOPTED if active else OwnershipStatus.UNMANAGED)


@pytest.mark.parametrize("tunnel_exists", [True, False])
def test_dry_run_never_provisions_writes_token_or_restarts(tunnel_exists):
    calls = []

    def cloudflare(endpoint, token, method="GET", data=None):
        calls.append((method, endpoint))
        assert method == "GET"
        if endpoint.startswith("/zones?"):
            return {"result": [{"id": "zone", "account": {"id": "account"}}]}
        if "/cfd_tunnel?" in endpoint:
            return {"result": [{"id": "tunnel"}] if tunnel_exists else []}
        if endpoint.endswith("/configurations"):
            return {"result": {"config": {"ingress": [{"service": "http_status:404"}]}}}
        assert not endpoint.endswith("/token")
        return {"result": []}

    state = {**app.sync_state, "logs": [], "events": [], "sync_history": [], "tombstones": {}, "docker_connected": True}
    with (
        patch.dict(
            os.environ, {"DRY_RUN": "true", "CLOUDFLARE_API_TOKEN": "dummy", "DOMAIN_NAME": "example.com"}, clear=True
        ),
        patch.object(app, "sync_state", state),
        patch.object(app, "cf_api", side_effect=cloudflare),
        patch.object(app, "get_docker_containers", return_value=([], [])),
        patch.object(app, "docker_api") as docker,
        patch("builtins.open") as token_file,
        patch("os.makedirs") as mkdir,
        patch.object(app, "default_dispatcher", Mock()),
    ):
        app.run_sync_logic()
    docker.assert_not_called()
    token_file.assert_not_called()
    mkdir.assert_not_called()
    assert "Dry-Run" in state["status"]
    assert calls
