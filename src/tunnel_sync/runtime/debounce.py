"""Coalesce lifecycle events without losing ownership of pending work."""

import asyncio
import inspect
import logging
import threading
import time
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


class DebouncedSyncTrigger:
    def __init__(
        self,
        delay: float = 2.5,
        max_delay: float = 10.0,
        sync_target: Optional[Callable] = None,
        log: Callable[[str], None] = lambda message: None,
    ):
        self.log = log
        self._closed = False
        self.delay = delay
        self.max_delay = max_delay
        self.sync_target = sync_target
        self._worker_task: Optional[asyncio.Task] = None
        self._deadline: Optional[float] = None
        self._max_deadline: Optional[float] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
        self._reasons: List[str] = []

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def trigger(self, reason: str = ""):
        with self._lock:
            if self._closed:
                return
            now = time.monotonic()
            if self._max_deadline is None:
                self._max_deadline = now + self.max_delay
            self._deadline = min(now + self.delay, self._max_deadline)

            if reason:
                self._reasons.append(reason)

            target_loop = self._loop
            if target_loop is None or not target_loop.is_running():
                try:
                    target_loop = asyncio.get_running_loop()
                except RuntimeError:
                    # No active event loop in current thread
                    pass

            if target_loop and target_loop.is_running():
                target_loop.call_soon_threadsafe(self._ensure_worker)

    def _ensure_worker(self):
        with self._lock:
            if not self._closed and (self._worker_task is None or self._worker_task.done()):
                self._worker_task = asyncio.create_task(self._coalescing_worker())

    async def _coalescing_worker(self):
        while True:
            with self._lock:
                now = time.monotonic()
                if self._deadline is None:
                    break
                remaining = self._deadline - now

            if remaining > 0:
                try:
                    await asyncio.sleep(remaining)
                except asyncio.CancelledError:
                    return

            with self._lock:
                now = time.monotonic()
                if self._deadline is not None and (self._deadline - now) > 0.005:
                    continue
                reasons_copy = list(self._reasons)
                self._deadline = None
                self._max_deadline = None
                self._reasons.clear()

            reason_str = ", ".join(reasons_copy[-3:]) if reasons_copy else "event trigger"
            self.log(f"Debounce window elapsed ({self.delay}s), executing sync: {reason_str}")
            try:
                if self.sync_target:
                    if inspect.iscoroutinefunction(self.sync_target):
                        await self.sync_target()
                    else:
                        await asyncio.to_thread(self.sync_target)
            except Exception as e:
                logger.error(f"Error during debounced sync: {e}")

    async def close(self):
        with self._lock:
            self._closed = True
            self._deadline = self._max_deadline = None
            self._reasons.clear()
            worker = self._worker_task
        if worker is not None and not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
