"""Isolated contracts for planner."""

from tests.fakes import remote
from tunnel_sync.domain.models import DiscoveredOrigin, DiscoverySnapshot
from tunnel_sync.domain.planner import compute_change_plan


def test_planner_is_deterministic_and_defensively_copies_nested_values():
    rules = [
        {"hostname": "manual.example.com", "path": "/a", "service": "http://a", "unknown": {"x": [1]}},
        {"hostname": "manual.example.com", "path": "/b", "service": "http://b"},
        {"hostname": "manual.example.com", "path": "/a", "service": "http://duplicate"},
        {"service": "http_status:403", "originRequest": {"httpHostHeader": "fallback"}},
    ]
    state = remote(rules)
    snapshot = DiscoverySnapshot(
        timestamp=42,
        docker_ok=True,
        origins=[
            DiscoveredOrigin(
                container_id="web",
                container_name="web",
                hostname="web.example.com",
                service_target="http://web:80",
                origin_request={"nested": {"items": [1]}},
            )
        ],
    )
    before = (snapshot.model_dump(), state.model_dump())
    first = compute_change_plan(snapshot, state, {}, now=42, plan_id="fixed")
    assert first == compute_change_plan(snapshot, state, {}, now=42, plan_id="fixed")
    assert first.final_ingress_rules[:3] == rules[:3]
    assert first.final_ingress_rules[-1] == rules[-1]
    first.final_ingress_rules[0]["unknown"]["x"].append(2)
    first.ingress_changes[0].origin_request["nested"]["items"].append(2)
    assert (snapshot.model_dump(), state.model_dump()) == before


def test_degraded_inventory_preserves_exact_ingress_without_reordering():
    rules = [
        {"hostname": "z.example.com", "path": "/x", "service": "http://z"},
        {"hostname": "a.example.com", "service": "http://a"},
        {"service": "http_status:403"},
    ]
    plan = compute_change_plan(
        DiscoverySnapshot(timestamp=1, docker_ok=False), remote(rules), {}, now=1, plan_id="fixed"
    )
    assert plan.final_ingress_rules == rules
    assert not plan.summary.has_mutations
