"""Compatible ASGI/CLI entry point. Composition lives in tunnel_sync.bootstrap."""

# ruff: noqa: F401
import asyncio
import logging
import os
import time
from types import SimpleNamespace

import uvicorn

from tunnel_sync.adapters.cloudflare import CloudflareReadAdapter, CloudflareWriteAdapter
from tunnel_sync.adapters.connector import DockerConnectorRestarter, FileTokenStore
from tunnel_sync.adapters.docker import (
    DockerAPIError,
    DockerClient,
    DockerReadAdapter,
    DockerUnavailableError,
    UnixHTTPConnection,
)
from tunnel_sync.application.discovery import DiscoveryService
from tunnel_sync.application.executor import ChangeExecutor
from tunnel_sync.application.preflight import PreflightService
from tunnel_sync.application.reporting import Reporter
from tunnel_sync.application.state import RuntimeState
from tunnel_sync.application.sync import SyncService
from tunnel_sync.bootstrap import create_services
from tunnel_sync.compat.cloudflare import cf_api as _cf_api
from tunnel_sync.configuration.settings import Settings
from tunnel_sync.domain.discovery import (
    NetworkPlausibilityResult,
    build_ingress_rules,
    evaluate_origin_network_plausibility,
    normalize_hostname,
)
from tunnel_sync.runtime.debounce import DebouncedSyncTrigger
from tunnel_sync.runtime.logging import (
    HealthCheckFilter,
    JsonLogFormatter,
    perform_startup_validation,
    setup_application_logging,
)
from tunnel_sync.runtime.scheduler import CONTAINER_LIFECYCLE_ACTIONS
from tunnel_sync.web.app import create_app, create_http_app


def _settings():
    return Settings(os.environ)


def get_domain_name():
    return _settings().domain


def get_token():
    return _settings().token


_runtime = RuntimeState(_settings())
sync_state = _runtime.data
sync_lock = _runtime.run_lock


def _reporter():
    return Reporter(sync_state, metrics_registry, default_dispatcher, _runtime.working_lock)


def add_log(msg):
    _reporter().add_log(msg)


def cf_api(endpoint, token, method="GET", data=None, paginate=True, max_retries=3):
    return _cf_api(
        endpoint, token, method=method, data=data, paginate=paginate, max_retries=max_retries, report_retry=add_log
    )


def record_event(severity, event_type, service, message):
    _reporter().record_event(severity, event_type, service, message)


def record_sync_history(duration_ms, status, services_count, summary=None):
    _reporter().record_sync_history(duration_ms, status, services_count, summary)


def update_overview_metrics():
    _reporter().update_overview_metrics()


def _docker():
    return DockerClient(
        _settings(),
        lambda connected: sync_state.__setitem__("docker_connected", connected),
        add_log,
        UnixHTTPConnection,
    )


def docker_api(path, method="GET", data=None, timeout=None, retries=None):
    try:
        return _docker().request(path, method=method, data=data, timeout=timeout, retries=retries)
    except DockerUnavailableError:
        return []


def _discovery():
    return DiscoveryService(_settings(), DockerReadAdapter(docker_api), sync_state, add_log)


def get_docker_containers():
    return _discovery().discover()


def resolve_target_connector_container(containers):
    return _discovery().resolve_target_connector_container(containers)


def find_cloudflared_container_name(containers=None):
    return _discovery().find_cloudflared_container_name(containers)


def run_sync_logic():
    _runtime.data = sync_state
    _runtime.run_lock = sync_lock
    reporter = _reporter()
    executor = ChangeExecutor(
        CloudflareWriteAdapter(cf_api),
        FileTokenStore(),
        DockerConnectorRestarter(docker_api),
        add_log,
        reporter.record_operation,
    )
    SyncService(
        _settings(),
        _runtime,
        CloudflareReadAdapter(cf_api),
        get_docker_containers,
        find_cloudflared_container_name,
        executor,
        reporter,
        metrics_registry,
        default_dispatcher,
        clock=time.time,
    ).run_once()


def listen_docker_events(on_event, stop_event=None, socket_path=None):
    return _docker().listen_events(on_event, stop_event, socket_path)


def run_preflight_validation(dry_run=True):
    discovery = SimpleNamespace(discover=get_docker_containers)
    return PreflightService(_settings(), CloudflareReadAdapter(cf_api), DockerReadAdapter(docker_api), discovery).run(
        dry_run
    )


# The default ASGI application uses the same independent composition as the factory.
_services = create_services(_settings(), runtime=_runtime)
metrics_registry = _services.metrics
default_dispatcher = _services.dispatcher
app = create_http_app(_services)
globals().update(app.state.handlers)
_http_ready = app.state.handlers["ready"]


def ready(response=None):
    """Retain direct calls without a Response; FastAPI injects it on HTTP requests."""
    return _http_ready(response)


debouncer = _services.scheduler.debouncer
handle_docker_event = _services.scheduler.handle_event
fallback_sync_loop = _services.scheduler.fallback_loop
sync_loop = fallback_sync_loop
logger = logging.getLogger("cf-tunnel-sync")
