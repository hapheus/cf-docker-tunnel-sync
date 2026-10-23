"""Composition root: construct independent services without opening connections."""

from dataclasses import dataclass

from tunnel_sync.adapters.cloudflare import CloudflareClient, CloudflareReadAdapter, CloudflareWriteAdapter
from tunnel_sync.adapters.connector import DockerConnectorRestarter, FileTokenStore
from tunnel_sync.adapters.docker import DockerClient, DockerReadAdapter
from tunnel_sync.adapters.metrics import PrometheusRegistry
from tunnel_sync.adapters.notifications import NotificationDispatcher
from tunnel_sync.adapters.retry import RetryPolicy
from tunnel_sync.application.discovery import DiscoveryService
from tunnel_sync.application.executor import ChangeExecutor
from tunnel_sync.application.preflight import PreflightService
from tunnel_sync.application.reporting import Reporter
from tunnel_sync.application.state import RuntimeState
from tunnel_sync.application.sync import SyncService
from tunnel_sync.configuration.settings import Settings
from tunnel_sync.runtime.scheduler import Scheduler


@dataclass
class Services:
    settings: Settings
    runtime: RuntimeState
    reporter: Reporter
    discovery: DiscoveryService
    sync: SyncService
    preflight: PreflightService
    scheduler: Scheduler
    metrics: PrometheusRegistry
    dispatcher: NotificationDispatcher

    def snapshot(self):
        return self.runtime.snapshot()

    def status(self):
        state = self.snapshot()
        Reporter(state, self.metrics, self.dispatcher).update_overview_metrics()
        return state

    def cache_preview(self, plan):
        return self.runtime.cache_preview(plan)


def create_services(
    settings: Settings, *, cloudflare_request=None, docker=None, token_store=None, dispatcher=None, runtime=None
) -> Services:
    runtime = runtime if runtime is not None else RuntimeState(settings)
    metrics = PrometheusRegistry()
    dispatcher = (
        dispatcher
        if dispatcher is not None
        else NotificationDispatcher(
            webhook_url=settings.get("NOTIFICATION_WEBHOOK_URL", ""),
            webhook_type=settings.get("NOTIFICATION_WEBHOOK_TYPE", "auto"),
            cooldown_seconds=_number(settings, "NOTIFICATION_COOLDOWN_SECONDS", 300.0),
            environment={},
            metrics=metrics,
        )
    )
    reporter = Reporter(runtime.data, metrics, dispatcher, runtime.working_lock)

    def report_connection(connected):
        with runtime.working_lock:
            runtime.data["docker_connected"] = connected
            runtime.publish()

    docker = docker if docker is not None else DockerClient(settings, report_connection, reporter.add_log)
    docker_reader = DockerReadAdapter(docker.request)
    discovery = DiscoveryService(settings, docker_reader, runtime.data, reporter.add_log, runtime.working_lock)
    if cloudflare_request is None:
        client = CloudflareClient(
            retry_policy=RetryPolicy(
                max_retries=int(_number(settings, "CLOUDFLARE_MAX_RETRIES", 3)),
                base_delay=_number(settings, "CLOUDFLARE_RETRY_BASE_DELAY", 0.5),
            ),
            metrics=metrics,
            report_retry=reporter.add_log,
            environment={},
        )
        cloudflare_request = client.sync_request
    reader = CloudflareReadAdapter(cloudflare_request)
    writer = CloudflareWriteAdapter(cloudflare_request)
    executor = ChangeExecutor(
        writer,
        token_store if token_store is not None else FileTokenStore(),
        DockerConnectorRestarter(docker.request),
        reporter.add_log,
        reporter.record_operation,
    )
    sync = SyncService(
        settings,
        runtime,
        reader,
        discovery.collect,
        discovery.find_cloudflared_container_name,
        executor,
        reporter,
        metrics,
        dispatcher,
    )
    preflight = PreflightService(settings, reader, docker_reader, discovery)
    scheduler = Scheduler(settings, sync.run_once, docker, reporter.add_log, state=runtime.data)
    return Services(settings, runtime, reporter, discovery, sync, preflight, scheduler, metrics, dispatcher)


def _number(settings, key, default):
    try:
        return float(settings.get(key, default))
    except (ValueError, TypeError):
        return default
