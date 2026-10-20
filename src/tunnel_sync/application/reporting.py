"""Redacted bounded events/history and observability publication."""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tunnel_sync.application.executor import OperationResult
from tunnel_sync.security import redact_sensitive_string

logger = logging.getLogger("cf-tunnel-sync")


class Reporter:
    def __init__(self, state, metrics, dispatcher, lock=None):
        self.state, self.metrics, self.dispatcher = state, metrics, dispatcher
        self.lock = lock if lock is not None else threading.RLock()

    def add_log(self, msg: str):
        with self.lock:
            safe_msg = redact_sensitive_string(msg)
            timestamp = time.strftime("%H:%M:%S")
            entry = f"[{timestamp}] {safe_msg}"
            logger.info(safe_msg)
            self.state["logs"].insert(0, entry)
            if len(self.state["logs"]) > 100:
                self.state["logs"].pop()

    def record_event(self, severity: str, event_type: str, service: str, message: str):
        """Record structured event in bounded ring-buffer with redaction (Issue #120)."""
        with self.lock:
            safe_msg = redact_sensitive_string(message)
            now = time.time()
            iso_time = datetime.now(timezone.utc).isoformat()
            event_id = f"evt-{int(now * 1000)}-{os.urandom(3).hex()}"
            evt = {
                "id": event_id,
                "timestamp": now,
                "iso_time": iso_time,
                "severity": severity.lower(),
                "event_type": event_type,
                "service": service or "-",
                "message": safe_msg,
            }
            self.state["events"].insert(0, evt)
            if len(self.state["events"]) > 100:
                self.state["events"].pop()

    def record_sync_history(
        self, duration_ms: float, status: str, services_count: int, summary: Optional[Dict[str, Any]] = None
    ):
        """Record sync cycle in bounded history ring-buffer (Issue #119)."""
        with self.lock:
            now = time.time()
            iso_time = datetime.now(timezone.utc).isoformat()
            entry = {
                "timestamp": now,
                "iso_time": iso_time,
                "duration_ms": round(duration_ms, 2),
                "status": status,
                "services_count": services_count,
                "summary": summary or {},
            }
            self.state["sync_history"].insert(0, entry)
            if len(self.state["sync_history"]) > 20:
                self.state["sync_history"].pop()

    def update_overview_metrics(self):
        """Compute high-level summary overview metrics (Issue #117)."""
        with self.lock:
            discovered = len(self.state.get("discovered_services") or [])
            active = 0
            failed = 0
            services = self.state.get("services") or []
            if isinstance(services, list):
                for s in services:
                    st = s.get("status", "") if isinstance(s, dict) else ""
                    if "Active" in st or "Synced" in st:
                        active += 1
                    elif "Degraded" in st or "Error" in st or "Failed" in st:
                        failed += 1
            elif isinstance(services, dict):
                for s in services.values():
                    st = s.get("status", "") if isinstance(s, dict) else ""
                    if "Active" in st or "Synced" in st:
                        active += 1
                    elif "Degraded" in st or "Error" in st or "Failed" in st:
                        failed += 1

            last_sync = self.state.get("last_sync")
            st_val = self.state.get("status", "")
            docker_ok = self.state.get("docker_connected", True)
            safety_tripped = self.state.get("safety_guard_tripped", False)

            if last_sync is None or st_val == "Initializing":
                health_state = "never_synced"
            elif not docker_ok:
                health_state = "degraded"
            elif safety_tripped or failed > 0 or "Error" in st_val or "Degraded" in st_val:
                health_state = "degraded"
            elif "Active" in st_val or "Synced" in st_val or st_val == "Waiting for changes...":
                health_state = "healthy"
            else:
                health_state = "unknown"

            last_duration_ms = 0.0
            if self.state.get("sync_history"):
                last_duration_ms = self.state["sync_history"][0].get("duration_ms", 0.0)

            try:
                self.state["alert_status"] = self.dispatcher.get_status()
            except Exception:
                pass

            self.state["overview_metrics"] = {
                "active_services": active,
                "discovered_services": discovered,
                "failed_services": failed,
                "last_sync_duration_ms": last_duration_ms,
                "safety_tripped": safety_tripped,
                "api_connected": docker_ok,
                "health_state": health_state,
            }
            self.metrics.set_gauge("cf_tunnel_docker_connected", 1.0 if docker_ok else 0.0)

    def record_operation(self, operation: OperationResult) -> None:
        resource, action, target = operation.resource, operation.action, operation.target
        if resource == "ingress":
            self.metrics.record_ingress_op("failed" if operation.status == "failed" else action, 1.0)
            if operation.status == "failed":
                message = f"Failed to update Cloudflare Ingress rules: {operation.reason}"
                self.record_event("error", "INGRESS_ERROR", "ingress", message)
                self.add_log(f"❌ {message}")
            else:
                self.record_event("info", "INGRESS_UPDATE", "ingress", "Updated Cloudflare Tunnel Ingress rules")
                self.add_log("✅ Updated Cloudflare Tunnel Ingress rules")
        elif operation.status == "failed":
            self.metrics.record_dns_op("failed", 1.0)
            self.record_event("error", "DNS_ERROR", target, f"DNS mutation failed for {target}: {operation.reason}")
            self.add_log(f"❌ DNS mutation failed for {target}: {operation.reason}")
        else:
            self.metrics.record_dns_op(action, 1.0)
            message = f"DNS {action} for {target}"
            self.record_event("info", f"DNS_{action.upper()}", target, message)
            if action == "delete":
                message = f"Deleted obsolete DNS record for {target} after grace period expired"
            self.add_log(message)
