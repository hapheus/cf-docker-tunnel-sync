"""Own startup, periodic sync, debounce tasks, and the Docker event thread."""

import asyncio
import threading

from tunnel_sync.runtime.debounce import DebouncedSyncTrigger

CONTAINER_LIFECYCLE_ACTIONS = {"start", "stop", "die", "kill", "destroy", "rename", "pause", "unpause", "restart"}


class Scheduler:
    def __init__(self, settings, run_once, events, log):
        self.settings, self.run_once, self.events, self.log = settings, run_once, events, log
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

    def handle_event(self, event: dict):
        if not isinstance(event, dict):
            return
        event_type = event.get("Type", "container")
        if event_type and event_type != "container":
            return

        action = event.get("Action", event.get("status", ""))
        base_action = action.split(":")[0].strip().lower()
        if base_action in CONTAINER_LIFECYCLE_ACTIONS:
            actor = event.get("Actor", {})
            attrs = actor.get("Attributes", {}) if isinstance(actor, dict) else {}
            container_name = attrs.get("name", event.get("id", "unknown")[:12])
            self.log(f"Container lifecycle event: {base_action} for {container_name}")
            self.debouncer.trigger(f"{base_action}:{container_name}")
