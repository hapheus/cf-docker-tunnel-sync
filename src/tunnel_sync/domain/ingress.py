"""Lossless merge of managed root routes into ordered remote ingress."""

from copy import deepcopy
from typing import Any


def merge_ingress(existing: list[dict[str, Any]], desired_roots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace the first root per hostname; preserve paths, duplicates, and catch-alls.

    The planner supplies preserved unmanaged roots alongside desired managed roots.
    New routes are inserted before the first hostname-less fallback.
    """
    pending = {rule["hostname"]: deepcopy(rule) for rule in desired_roots}
    result: list[dict[str, Any]] = []
    seen = set()
    for original in existing:
        host = original.get("hostname")
        if not host:
            result.extend(pending.pop(hostname) for hostname in sorted(pending))
            result.append(deepcopy(original))
        elif original.get("path") or host in seen:
            result.append(deepcopy(original))
        else:
            seen.add(host)
            desired = pending.pop(host, None)
            if desired is not None:
                replacement = deepcopy(original)
                replacement.pop("originRequest", None)
                replacement.update(desired)
                result.append(replacement)
    result.extend(pending[host] for host in sorted(pending))
    if not any(not rule.get("hostname") for rule in result):
        result.append({"service": "http_status:404"})
    return result
