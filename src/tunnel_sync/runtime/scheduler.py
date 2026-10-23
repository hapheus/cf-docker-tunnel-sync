"""Own startup, periodic sync, debounce tasks, and the Docker event thread."""

import asyncio
import threading

from tunnel_sync.domain.labels import has_tunnel_labels
from tunnel_sync.runtime.debounce import DebouncedSyncTrigger

CONTAINER_LIFECYCLE_ACTIONS = {"start", "stop", "die", "destroy", "rename", "pause", "unpause", "restart"}


class Scheduler:
    def __init__(self, settings, run_once, events, log, state=None):
        self.settings, self.run_once, self.events, self.log = settings, run_once, events, log
        self.state = state
        self.filter_unlabeled_events = str(settings.get("FILTER_UNLABELED_EVENTS", "true")).strip().lower() not in (
            "false",
            "0",
            "no",
        )
        self.debouncer = DebouncedSyncTrigger(
            delay=float(settings.get("SYNC_DEBOUNCE_SECONDS", settings.get("SYNC_DEBOUNCE_DELAY", 2.5))),
            max_delay=float(settings.get("SYNC_DEBOUNCE_MAX_DELAY", 10.0)),
            sync_target=self.run_sync,
            log=log,
        )
        self.stop_event = threading.Event()
        self.thread = None
        self.periodic = None
        self.tasks = set()
        self.closed = False
        self.started = False

    async def run_sync(self):
        if self.closed:
            return
        task = asyncio.create_task(asyncio.to_thread(self.run_once))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        await asyncio.shield(task)

    async def fallback_loop(self):
        while not self.closed:
            try:
                interval = int(
                    self.settings.get(
                        "SYNC_FALLBACK_INTERVAL",
                        self.settings.get("SYNC_INTERVAL", self.settings.get("POLL_INTERVAL", 900)),
                    )
                )
                await asyncio.sleep(interval)
                self.log("Fallback periodic heartbeat sync triggered")
                await self.run_sync()
            except asyncio.CancelledError:
                return
            except Exception as error:
                self.log(f"Unexpected loop exception: {error}")

    async def start(self):
        if self.closed:
            raise RuntimeError("A closed scheduler cannot be restarted")
        if self.started:
            return
        self.started = True
        self.debouncer.set_loop(asyncio.get_running_loop())
        initial = asyncio.create_task(self.run_sync())
        self.tasks.add(initial)
        initial.add_done_callback(self.tasks.discard)
        self.thread = threading.Thread(
            target=self.events.listen_events,
            args=(self.handle_event, self.stop_event),
            daemon=True,
            name="docker-events-listener",
        )
        self.thread.start()
        self.periodic = asyncio.create_task(self.fallback_loop())

    async def close(self, timeout=45.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        self.closed = True
        self.stop_event.set()
        await self.debouncer.close()
        if self.periodic:
            self.periodic.cancel()
            await asyncio.gather(self.periodic, return_exceptions=True)
        self.events.close_events()
        if self.thread:
            await asyncio.to_thread(self.thread.join, max(0.0, deadline - loop.time()))
            if self.thread.is_alive():
                raise RuntimeError("Docker event listener did not stop within shutdown timeout")
        pending = list(self.tasks)
        if pending:
            _, remaining = await asyncio.wait(pending, timeout=max(0.0, deadline - loop.time()))
            if remaining:
                raise RuntimeError("In-flight synchronization exceeded shutdown timeout")

    def is_relevant_event(self, event: dict, base_action: str) -> bool:
        """Determine if a container lifecycle event warrants triggering a sync."""
        if not self.filter_unlabeled_events:
            return True

        actor = event.get("Actor", {})
        attrs = actor.get("Attributes", {}) if isinstance(actor, dict) else {}

        # 1. Container has recognized tunnel configuration labels
        if has_tunnel_labels(attrs):
            return True

        # 2. Cloudflared connector container itself (restarts/dies affect tunnel health & IP)
        connector_target = (self.settings.get("CLOUDFLARED_CONTAINER_NAME") or "cloudflared").strip().lower()
        c_name = str(attrs.get("name", "")).lstrip("/").lower()
        compose_service = str(attrs.get("com.docker.compose.service", "")).lower()
        event_id = str(event.get("id", "")).lower()

        if (
            c_name == connector_target
            or compose_service == connector_target
            or (len(connector_target) >= 12 and event_id.startswith(connector_target))
            or c_name == "cloudflared"
            or compose_service == "cloudflared"
        ):
            return True

        # 3. Container was previously active in our tracked services (tombstone / deletion case)
        if self.state and isinstance(self.state, dict):
            for svc in self.state.get("services") or []:
                if isinstance(svc, dict):
                    svc_name = str(svc.get("name", "")).lstrip("/").lower()
                    svc_container = str(svc.get("container", "")).lstrip("/").lower()
                    if c_name and (c_name == svc_name or c_name == svc_container):
                        return True
                    if event_id and (
                        (svc_name and event_id.startswith(svc_name))
                        or (svc_container and event_id.startswith(svc_container))
                    ):
                        return True

        return False

    def handle_event(self, event: dict):
        if not isinstance(event, dict):
            return
        event_type = event.get("Type", "container")
        if event_type and event_type != "container":
            return

        action = event.get("Action", event.get("status", ""))
        base_action = action.split(":")[0].strip().lower()
        if base_action in CONTAINER_LIFECYCLE_ACTIONS:
            if not self.is_relevant_event(event, base_action):
                return
            actor = event.get("Actor", {})
            attrs = actor.get("Attributes", {}) if isinstance(actor, dict) else {}
            container_name = attrs.get("name", event.get("id", "unknown")[:12])
            self.log(f"Container lifecycle event: {base_action} for {container_name}")
            self.debouncer.trigger(f"{base_action}:{container_name}")
