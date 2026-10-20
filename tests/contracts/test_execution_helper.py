"""Isolated contracts for execution helper."""

from tests.fakes import FakeCloudflare, remote
from tunnel_sync.domain.models import DiscoveredOrigin, DiscoverySnapshot
from tunnel_sync.domain.planner import compute_change_plan


def test_legacy_execution_helper_preserves_enclosing_remote_configuration():
    from reconcile import execute_change_plan

    cf = FakeCloudflare()
    snapshot = DiscoverySnapshot(
        timestamp=1,
        docker_ok=True,
        origins=[
            DiscoveredOrigin(
                container_id="web", container_name="web", hostname="web.example.com", service_target="http://web:80"
            )
        ],
    )
    plan = compute_change_plan(snapshot, remote(cf.config["ingress"]), {}, now=1, plan_id="fixed")
    execute_change_plan(plan, "dummy", "account", cf.request)
    assert cf.config["warp-routing"] == {"enabled": True}
    assert cf.config["ingress"][0]["hostname"] == "web.example.com"
