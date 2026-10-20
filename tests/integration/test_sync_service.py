"""Isolated contracts for sync service."""

import threading

import pytest
from starlette.testclient import TestClient

from tests.fakes import FakeCloudflare, FakeDocker, composition
from tunnel_sync.application.inventory import InventoryStatus
from tunnel_sync.web.app import create_http_app


@pytest.mark.parametrize("tunnel_exists", [True, False])
def test_independent_dry_run_has_no_external_writes(tunnel_exists):
    services, cf, docker, store = composition(cloudflare=FakeCloudflare(tunnel_exists), DRY_RUN="true")
    services.sync.run_once()
    assert not cf.mutations
    assert not store.writes and store.reads == 0
    assert not docker.restarts
    assert "Dry-Run" in services.snapshot()["status"]


def test_dry_run_read_failure_does_not_send_webhook_notifications():
    services, cf, _, _ = composition(DRY_RUN="true")

    class Notifications:
        def dispatch_sync(self, **kwargs):
            pytest.fail("Dry-run must not dispatch a webhook even after a read failure")

    class FailedReader:
        def read(self, *args, **kwargs):
            raise ConnectionError("Cloudflare read unavailable")

    services.sync.dispatcher = Notifications()
    services.sync.cloudflare = FailedReader()
    services.sync.run_once()
    assert "Error:" in services.snapshot()["status"]
    assert not cf.mutations


def test_provision_uses_real_id_and_repeated_sync_converges_then_repairs_drift():
    services, cf, docker, store = composition(cloudflare=FakeCloudflare(False))
    services.sync.run_once()
    assert store.writes == ["new-token"]
    assert len(docker.restarts) == 1
    assert services.snapshot()["tunnel_id"] == "real-tunnel"
    assert cf.config["warp-routing"] == {"enabled": True}
    mutations = len(cf.mutations)
    services.sync.run_once()
    assert len(cf.mutations) == mutations
    cf.config["ingress"][0]["service"] = "http://drift:80"
    services.sync.run_once()
    assert len(cf.mutations) == mutations + 1
    assert cf.config["ingress"][0]["service"] == "http://web:80"


def test_ingress_failure_continues_dns_and_recovers_next_cycle():
    services, cf, _, _ = composition()
    cf.fail_ingress = True
    services.sync.run_once()
    assert cf.dns and services.snapshot()["status"] == "Degraded"
    assert any(event["event_type"] == "INGRESS_ERROR" for event in services.snapshot()["events"])
    cf.fail_ingress = False
    services.sync.run_once()
    assert services.snapshot()["status"] == "Active / Synced"
    assert len(cf.dns) == 1


def test_failed_deletion_preserves_expired_tombstone_until_retry_succeeds():
    services, cf, docker, _ = composition(DNS_CLEANUP_GRACE_PERIOD="10")
    services.sync.clock = lambda: 100.0
    services.sync.run_once()
    docker.containers = []
    services.sync.run_once()
    assert services.snapshot()["tombstones"] == {"web.example.com": 100.0}
    services.sync.clock = lambda: 120.0
    cf.fail_dns = True
    services.sync.run_once()
    assert services.snapshot()["tombstones"] == {"web.example.com": 100.0}
    cf.fail_dns = False
    services.sync.run_once()
    assert services.snapshot()["tombstones"] == {}
    assert cf.dns == []


def test_unavailable_inventory_blocks_provisioning_and_activation():
    services, cf, docker, store = composition(cloudflare=FakeCloudflare(False), docker=FakeDocker(unavailable=True))
    services.sync.run_once()
    assert services.snapshot()["status"] == "Docker connection degraded"
    assert not cf.mutations and not store.writes and not docker.restarts


def test_inventory_recovers_to_successful_empty_after_failure():
    services, _, docker, _ = composition(docker=FakeDocker(unavailable=True))
    assert not services.discovery.collect().usable
    docker.unavailable = False
    docker.containers = []
    inventory = services.discovery.collect()
    assert inventory.status == InventoryStatus.AVAILABLE
    assert inventory.services == ()


@pytest.mark.parametrize("available", [True, False])
@pytest.mark.parametrize("path", ["/api/sync/preview", "/api/change-plan"])
def test_preview_uses_current_inventory_availability_after_connection_changes(available, path):
    services, cf, docker, store = composition()
    services.runtime.data["docker_connected"] = not available
    services.runtime.publish()
    docker.unavailable = not available
    client = TestClient(create_http_app(services))
    response = client.get(path)
    assert response.status_code == 200
    if path == "/api/sync/preview":
        assert response.json()["plan"]["summary"]["total_services_discovered"] == int(available)
    else:
        assert response.json()["summary"]["additions"] == 2 * int(available)
    assert not cf.calls and not store.writes and not docker.restarts


def test_status_reads_and_concurrent_sync_do_not_wait_for_provider_io():
    entered, release = threading.Event(), threading.Event()
    cf = FakeCloudflare()
    request = cf.request

    def blocked_request(endpoint, *args, **kwargs):
        if endpoint.endswith("/configurations") and kwargs.get("method", "GET") == "GET":
            entered.set()
            assert release.wait(3)
        return request(endpoint, *args, **kwargs)

    cf.request = blocked_request
    services, _, _, _ = composition(cloudflare=cf)
    client = TestClient(create_http_app(services))
    worker = threading.Thread(target=services.sync.run_once)
    worker.start()
    try:
        assert entered.wait(1)
        # These calls run while the provider read is still blocked.
        assert client.get("/api/status").json()["status"] == "Initializing"
        services.sync.run_once()
        assert not release.is_set()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert client.get("/api/status").json()["status"] == "Active / Synced"


def test_safety_trip_is_cleared_after_a_successful_retry():
    services, cf, _, _ = composition(docker=FakeDocker(), DNS_IMMEDIATE_CLEANUP="true")
    cf.dns = [
        {
            "id": f"dns-{number}",
            "type": "CNAME",
            "name": f"old{number}.example.com",
            "content": "real-tunnel.cfargotunnel.com",
            "comment": "cf-tunnel-sync:cf-docker-tunnel-sync",
        }
        for number in range(4)
    ]
    services.sync.run_once()
    assert services.snapshot()["safety_guard_tripped"]
    cf.dns.pop()
    services.sync.run_once()
    assert services.snapshot()["status"] == "Active / Synced"
    assert not services.snapshot()["safety_guard_tripped"]
    assert services.snapshot()["safety_details"] is None
