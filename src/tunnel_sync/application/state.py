"""Per-instance working state and detached snapshots."""

import threading
from copy import deepcopy


def initial_state(settings):

    return {
        "last_sync": None,
        "status": "Initializing",
        "tunnel_id": None,
        "tunnel_name": settings.get("CLOUDFLARE_TUNNEL_NAME", "cf-docker-tunnel-sync").strip(),
        "domain_name": settings.domain,
        "services": [],
        "discovered_services": [],
        "all_containers": [],
        "dns_records": [],
        "logs": [],
        "docker_connected": True,
        "tombstones": {},
        "last_change_plan": None,
        "safety_guard_tripped": False,
        "safety_details": None,
        "sync_history": [],
        "events": [],
        "alert_status": {
            "configured": False,
            "provider": "none",
            "last_delivery_success": None,
            "last_delivery_time": None,
            "last_delivery_status": None,
            "consecutive_failures": 0,
            "cooldown_active": False,
            "cooldown_seconds": 300.0,
        },
        "overview_metrics": {
            "active_services": 0,
            "discovered_services": 0,
            "failed_services": 0,
            "last_sync_duration_ms": 0.0,
            "safety_tripped": False,
            "api_connected": True,
            "health_state": "never_synced",
        },
    }


class RuntimeState:
    def __init__(self, settings):
        self.data = initial_state(settings)
        self.run_lock = threading.Lock()
        self.working_lock = threading.RLock()
        self.publication_lock = threading.RLock()
        self._published = deepcopy(self.data)

    def publish(self):
        with self.working_lock, self.publication_lock:
            self._published = deepcopy(self.data)

    def snapshot(self):
        with self.publication_lock:
            return deepcopy(self._published)

    def cache_preview(self, plan):
        """Retain fallback caching without replacing a newer live plan."""
        with self.working_lock:
            existing = self.data.get("_last_change_plan_obj")
            if existing is not None:
                return existing.model_copy(deep=True)
            self.data["_last_change_plan_obj"] = plan.model_copy(deep=True)
            self.data["last_change_plan"] = plan.model_dump()
            self.publish()
            return plan.model_copy(deep=True)
