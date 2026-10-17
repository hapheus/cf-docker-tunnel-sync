from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel


class DiagnosticStageName(str, Enum):
    LABEL_SYNTAX = "LABEL_SYNTAX"
    TUNNEL_DOMAIN_MATCH = "TUNNEL_DOMAIN_MATCH"
    NETWORK_TOPOLOGY = "NETWORK_TOPOLOGY"
    CLOUDFLARE_INGRESS = "CLOUDFLARE_INGRESS"
    CLOUDFLARE_DNS = "CLOUDFLARE_DNS"
    ORIGIN_HEALTH = "ORIGIN_HEALTH"


class DiagnosticStageStatus(str, Enum):
    PASS = "PASS"
    FAILED = "FAILED"
    WARNING = "WARNING"
    PENDING = "PENDING"
    SKIPPED = "SKIPPED"
    UNKNOWN = "UNKNOWN"


class StageResult(BaseModel):
    status: DiagnosticStageStatus
    message: str


def evaluate_service_stages(
    hostname: Optional[str],
    raw_hostname: Optional[str],
    is_hostname_valid: bool,
    domain_matches: bool,
    configured_domain: str,
    network_connected: bool,
    network_warning: Optional[str] = None,
    container_state: str = "running",
    ingress_status: Optional[str] = None,
    ingress_message: Optional[str] = None,
    dns_status: Optional[str] = None,
    dns_message: Optional[str] = None,
) -> Dict[str, Dict[str, str]]:
    """Evaluates the 6-stage diagnostic pipeline for a service origin."""
    stages: Dict[str, Dict[str, str]] = {}

    # Stage 1: LABEL_SYNTAX
    if is_hostname_valid and hostname:
        stages[DiagnosticStageName.LABEL_SYNTAX.value] = {
            "status": DiagnosticStageStatus.PASS.value,
            "message": f"Hostname '{hostname}' and label syntax valid",
        }
    else:
        stages[DiagnosticStageName.LABEL_SYNTAX.value] = {
            "status": DiagnosticStageStatus.FAILED.value,
            "message": f"Invalid label syntax or hostname '{raw_hostname or ''}' (RFC 1123 required)",
        }

    # Stage 2: TUNNEL_DOMAIN_MATCH
    if domain_matches:
        stages[DiagnosticStageName.TUNNEL_DOMAIN_MATCH.value] = {
            "status": DiagnosticStageStatus.PASS.value,
            "message": f"Hostname matches domain '{configured_domain}'",
        }
    else:
        stages[DiagnosticStageName.TUNNEL_DOMAIN_MATCH.value] = {
            "status": DiagnosticStageStatus.FAILED.value,
            "message": f"Hostname '{hostname}' does not match configured DOMAIN_NAME '{configured_domain}'",
        }

    # Stage 3: NETWORK_TOPOLOGY
    if network_connected:
        stages[DiagnosticStageName.NETWORK_TOPOLOGY.value] = {
            "status": DiagnosticStageStatus.PASS.value,
            "message": "Shared Docker network verified with cloudflared",
        }
    else:
        stages[DiagnosticStageName.NETWORK_TOPOLOGY.value] = {
            "status": DiagnosticStageStatus.WARNING.value,
            "message": network_warning or "Missing shared network with cloudflared (potential 502 Bad Gateway)",
        }

    # Stage 4: CLOUDFLARE_INGRESS
    if ingress_status:
        stages[DiagnosticStageName.CLOUDFLARE_INGRESS.value] = {
            "status": ingress_status,
            "message": ingress_message or "Ingress rule status updated",
        }
    else:
        stages[DiagnosticStageName.CLOUDFLARE_INGRESS.value] = {
            "status": DiagnosticStageStatus.PENDING.value,
            "message": "Pending ingress synchronization",
        }

    # Stage 5: CLOUDFLARE_DNS
    if dns_status:
        stages[DiagnosticStageName.CLOUDFLARE_DNS.value] = {
            "status": dns_status,
            "message": dns_message or "DNS record status updated",
        }
    else:
        stages[DiagnosticStageName.CLOUDFLARE_DNS.value] = {
            "status": DiagnosticStageStatus.PENDING.value,
            "message": "Pending DNS synchronization",
        }

    # Stage 6: ORIGIN_HEALTH
    if container_state.lower() in ("running", "healthy"):
        stages[DiagnosticStageName.ORIGIN_HEALTH.value] = {
            "status": DiagnosticStageStatus.PASS.value,
            "message": f"Container origin is {container_state}",
        }
    elif container_state.lower() in ("restarting", "created"):
        stages[DiagnosticStageName.ORIGIN_HEALTH.value] = {
            "status": DiagnosticStageStatus.WARNING.value,
            "message": f"Container origin in transitional state: {container_state}",
        }
    else:
        stages[DiagnosticStageName.ORIGIN_HEALTH.value] = {
            "status": DiagnosticStageStatus.FAILED.value,
            "message": f"Container origin is not running ({container_state})",
        }

    return stages


def compute_truthful_service_status(stages: Dict[str, Dict[str, str]]) -> str:
    """Computes truthful service status enum ('Synced', 'Degraded', 'Failed', 'Pending').

    Strict rule: Never report 'Synced' if any upstream stage (1-5) failed.
    If Ingress (stage 4) or DNS (stage 5) failed, marks as 'Degraded' (or 'Failed').
    """
    stage_1 = stages.get(DiagnosticStageName.LABEL_SYNTAX.value, {}).get("status")
    stage_2 = stages.get(DiagnosticStageName.TUNNEL_DOMAIN_MATCH.value, {}).get("status")
    stage_3 = stages.get(DiagnosticStageName.NETWORK_TOPOLOGY.value, {}).get("status")
    stage_4 = stages.get(DiagnosticStageName.CLOUDFLARE_INGRESS.value, {}).get("status")
    stage_5 = stages.get(DiagnosticStageName.CLOUDFLARE_DNS.value, {}).get("status")

    if (
        stage_1 == DiagnosticStageStatus.FAILED.value
        or stage_2 == DiagnosticStageStatus.FAILED.value
        or stage_3 == DiagnosticStageStatus.FAILED.value
    ):
        return "Failed"

    if stage_4 == DiagnosticStageStatus.FAILED.value or stage_5 == DiagnosticStageStatus.FAILED.value:
        return "Degraded"

    if stage_4 == DiagnosticStageStatus.PENDING.value or stage_5 == DiagnosticStageStatus.PENDING.value:
        return "Pending"

    if (
        stage_1 == DiagnosticStageStatus.PASS.value
        and stage_2 == DiagnosticStageStatus.PASS.value
        and stage_4 == DiagnosticStageStatus.PASS.value
        and stage_5 == DiagnosticStageStatus.PASS.value
    ):
        return "Synced"

    return "Degraded"
