"""Isolated contracts for executor."""

import pytest

from tests.fakes import remote
from tunnel_sync.application.executor import ChangeExecutor, DeletionPolicy
from tunnel_sync.domain.models import DiscoverySnapshot
from tunnel_sync.domain.planner import compute_change_plan


def test_executor_dry_run_does_not_need_writer_or_activation_dependencies():
    plan = compute_change_plan(
        DiscoverySnapshot(timestamp=1, docker_ok=True), remote([]), {}, now=1, plan_id="fixed", dry_run=True
    )
    executor = ChangeExecutor(None, None, None, lambda message: None)
    assert executor.provision("account", "name", "dummy", dry_run=True) is None
    executor.activate("token", lambda: pytest.fail("No connector lookup"), dry_run=True)
    assert not executor.execute(plan, "dummy", "account", policy=DeletionPolicy()).operations
