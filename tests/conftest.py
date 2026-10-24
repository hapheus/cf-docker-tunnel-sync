"""Bridge historical module-patching tests at their fixture boundary.

Production ASGI apps use frozen settings, detached snapshots, and injected services.
The older compatibility tests deliberately exercise the historical app helpers.
New service tests construct their own instances and need none of these patches.
"""

import os
from copy import deepcopy
from types import SimpleNamespace

import pytest

import app
from metrics import metrics_registry


@pytest.fixture(autouse=True)
def legacy_module_contract(monkeypatch):
    def cache_preview(plan):
        app.sync_state["_last_change_plan_obj"] = plan
        app.sync_state["last_change_plan"] = plan.model_dump()
        return plan

    monkeypatch.setattr(app._services, "settings", SimpleNamespace(get=os.getenv))
    monkeypatch.setattr(app._services, "snapshot", lambda: deepcopy(app.sync_state))
    monkeypatch.setattr(app._services, "cache_preview", cache_preview)
    monkeypatch.setattr(
        app._services,
        "discovery",
        SimpleNamespace(discover=app.get_docker_containers, collect=app.get_docker_containers),
    )
    monkeypatch.setattr(app._services, "reporter", SimpleNamespace(update_overview_metrics=app.update_overview_metrics))
    monkeypatch.setattr(app._services.scheduler, "run_once", app.run_sync_logic)
    monkeypatch.setattr(app._services, "metrics", metrics_registry)
    monkeypatch.setattr(app, "metrics_registry", metrics_registry)
