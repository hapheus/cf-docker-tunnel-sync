from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class OriginRequestConfig(BaseModel):
    """Origin request options for Cloudflare Tunnel ingress."""

    noTLSVerify: Optional[bool] = None
    originServerName: Optional[str] = None
    httpHostHeader: Optional[str] = None


class DiscoveredService(BaseModel):
    """Metadata representing a service discovered from container labels."""

    container: str
    hostname: str
    service: str
    no_tls_verify: bool = False
    network_connected: bool = True
    network_warning: Optional[str] = None
    originRequest: Optional[Dict[str, Any]] = None


class ContainerItem(BaseModel):
    """Status summary of a local Docker container."""

    name: str
    image: str
    state: str
    status: str
    hostname: str = "-"
    is_tunneled: bool = False
    network_connected: bool = True


class DNSRecordItem(BaseModel):
    """DNS CNAME record managed by the synchronizer."""

    hostname: str
    target: str
    service: Optional[str] = None
    proxied: bool = True
    tombstone_remaining: Optional[int] = None


class SyncStateModel(BaseModel):
    """State model for the synchronization engine."""

    last_sync: Optional[str] = None
    status: str = "Initializing"
    tunnel_id: Optional[str] = None
    tunnel_name: str = "cf-docker-tunnel-sync"
    domain_name: str = ""
    discovered_services: List[Dict[str, Any]] = Field(default_factory=list)
    all_containers: List[Dict[str, Any]] = Field(default_factory=list)
    dns_records: List[Dict[str, Any]] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)
    docker_connected: bool = True
    tombstones: Dict[str, float] = Field(default_factory=dict)
    last_change_plan: Optional[Dict[str, Any]] = None
