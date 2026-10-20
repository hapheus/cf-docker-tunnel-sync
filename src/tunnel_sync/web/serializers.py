"""Public ChangePlan presentation; independent of planner decisions."""

from typing import Any, Dict, List

from tunnel_sync.domain.models import ChangePlan
from tunnel_sync.security import SENSITIVE_KEY_SUBSTRINGS, redact_sensitive_string


def serialize_change_plan(plan: ChangePlan) -> Dict[str, Any]:
    """Returns JSON schema representation of the ChangePlan for the /api/change-plan endpoint."""
    actions: List[Dict[str, Any]] = []

    for ing in plan.ingress_changes:
        actions.append(
            {
                "action": ing.action.value.upper(),
                "resource": "INGRESS",
                "target": {
                    "hostname": ing.hostname,
                    "service": ing.service,
                    "path": ing.path,
                    "origin_request": ing.origin_request,
                },
                "reason": ing.reason,
            }
        )

    for dns in plan.dns_changes:
        actions.append(
            {
                "action": dns.action.value.upper(),
                "resource": "DNS",
                "target": {
                    "hostname": dns.hostname,
                    "record_id": dns.record_id,
                    "record_type": dns.record_type,
                    "current_content": dns.current_content,
                    "target_content": dns.target_content,
                    "proxied": dns.proxied,
                    "ttl": dns.ttl,
                },
                "reason": dns.reason,
            }
        )

    unmanaged = getattr(plan.summary, "unmanaged_skipped", 0) or plan.summary.dns_protected
    return {
        "plan_id": plan.plan_id,
        "dry_run": plan.dry_run,
        "timestamp": plan.timestamp,
        "actions": actions,
        "summary": {
            "additions": plan.summary.ingress_creates + plan.summary.dns_creates,
            "updates": plan.summary.ingress_updates + plan.summary.dns_updates,
            "deletions": plan.summary.ingress_deletes + plan.summary.dns_deletes,
            "unmanaged_skipped": unmanaged,
        },
    }


def sanitize_sync_state(data: Any) -> Any:
    """Return a safely JSON-serializable public representation of sync state.

    Excludes internal private keys (starting with '_') from dictionaries and
    recursively converts non-serializable collections (such as set and frozenset)
    into sorted lists, while redacting sensitive tokens and credentials.
    """
    if isinstance(data, dict):
        items = list(data.items())
        res = {}
        for k, v in items:
            if not k.startswith("_"):
                k_lower = str(k).lower()
                if any(sub in k_lower for sub in SENSITIVE_KEY_SUBSTRINGS):
                    res[k] = "[REDACTED]"
                else:
                    res[k] = sanitize_sync_state(v)
        return res
    elif isinstance(data, (set, frozenset)):
        items = list(data)
        try:
            return sorted(sanitize_sync_state(x) for x in items)
        except TypeError:
            return [sanitize_sync_state(x) for x in items]
    elif isinstance(data, (list, tuple)):
        items = list(data)
        return [sanitize_sync_state(x) for x in items]
    elif isinstance(data, str):
        return redact_sensitive_string(data)
    return data
