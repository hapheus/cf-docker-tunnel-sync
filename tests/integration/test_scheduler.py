"""Isolated contracts for scheduler."""

import asyncio
import threading

import pytest

from tests.fakes import FakeDocker
from tunnel_sync.configuration.settings import Settings
from tunnel_sync.runtime.scheduler import Scheduler


@pytest.mark.asyncio
async def test_scheduler_closes_listener_debounce_and_waits_for_inflight_sync():
    entered, release = threading.Event(), threading.Event()
    docker = FakeDocker()

    def run():
        entered.set()
        assert release.wait(2)

    scheduler = Scheduler(Settings({}), run, docker, lambda message: None)
    await scheduler.start()
    assert await asyncio.to_thread(entered.wait, 1)
    await scheduler.start()
    scheduler.debouncer.trigger("pending")
    closing = asyncio.create_task(scheduler.close(timeout=2))
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    _ = await closing
    assert docker.closed and not scheduler.thread.is_alive()
    assert not scheduler.tasks
    assert scheduler.debouncer._worker_task is None or scheduler.debouncer._worker_task.done()
    scheduler.debouncer.trigger("after shutdown")
    assert scheduler.debouncer._deadline is None
