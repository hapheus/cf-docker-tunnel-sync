import asyncio
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import app


class TestEventDrivenSync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["docker_connected"] = True
        app.sync_state["logs"] = []

    async def test_debouncer_bundles_rapid_events(self):
        """Verify that rapid successive events are bundled into a single sync execution."""
        mock_sync = MagicMock()
        debouncer = app.DebouncedSyncTrigger(delay=0.15, sync_target=mock_sync)
        debouncer.set_loop(asyncio.get_running_loop())

        # Trigger 5 rapid events in succession within a few milliseconds
        for i in range(5):
            debouncer.trigger(f"event_{i}")
            await asyncio.sleep(0.001)

        # Allow debounce window to elapse
        await asyncio.sleep(0.20)

        # Ensure sync callback was executed exactly ONCE
        self.assertEqual(mock_sync.call_count, 1)

    async def test_debouncer_respects_max_delay(self):
        """Verify that a steady stream of events does not starve sync past max_delay."""
        mock_sync = MagicMock()
        debouncer = app.DebouncedSyncTrigger(delay=0.10, max_delay=0.20, sync_target=mock_sync)
        debouncer.set_loop(asyncio.get_running_loop())

        start_time = time.time()
        # Continuously trigger events every 0.03s for 0.35s
        while time.time() - start_time < 0.35:
            debouncer.trigger("continuous_event")
            await asyncio.sleep(0.03)

        await asyncio.sleep(0.15)
        # Should have executed at least once despite constant triggers
        self.assertGreaterEqual(mock_sync.call_count, 1)

    def test_handle_docker_event_filters(self):
        """Verify handle_docker_event triggers on relevant container lifecycle actions and ignores unlabelled/others."""
        with patch.object(app.debouncer, "trigger") as mock_trigger:
            # 1. Container with cf.tunnel.hostname start event -> should trigger
            app.handle_docker_event(
                {
                    "Type": "container",
                    "Action": "start",
                    "Actor": {"Attributes": {"name": "web-nginx", "cf.tunnel.hostname": "web.example.com"}},
                }
            )
            mock_trigger.assert_called_with("start:web-nginx")

            # 2. Container with cloudflared.* label stop event -> should trigger
            mock_trigger.reset_mock()
            app.handle_docker_event(
                {
                    "Type": "container",
                    "Action": "stop",
                    "Actor": {"Attributes": {"name": "api-service", "cloudflared.port": "8080"}},
                }
            )
            mock_trigger.assert_called_with("stop:api-service")

            # 3. Cloudflared connector container itself (without tunnel labels) -> should trigger
            mock_trigger.reset_mock()
            app.handle_docker_event(
                {"Type": "container", "Action": "restart", "Actor": {"Attributes": {"name": "cloudflared"}}}
            )
            mock_trigger.assert_called_with("restart:cloudflared")

            # 4. Container without labels (e.g. db-postgres) -> must be IGNORED
            mock_trigger.reset_mock()
            app.handle_docker_event(
                {"Type": "container", "Action": "start", "Actor": {"Attributes": {"name": "db-postgres"}}}
            )
            mock_trigger.assert_not_called()

            # 5. Container without labels stop -> must be IGNORED
            mock_trigger.reset_mock()
            app.handle_docker_event(
                {"Type": "container", "Action": "stop", "Actor": {"Attributes": {"name": "db-postgres"}}}
            )
            mock_trigger.assert_not_called()

            # 6. Container action 'kill' -> must be IGNORED (even with labels, waiting for die/stop)
            mock_trigger.reset_mock()
            app.handle_docker_event(
                {
                    "Type": "container",
                    "Action": "kill",
                    "Actor": {"Attributes": {"name": "web-nginx", "cf.tunnel.hostname": "web.example.com"}},
                }
            )
            mock_trigger.assert_not_called()

            # 7. Previously tracked active container in state, deleted/died even without attributes -> should trigger
            mock_trigger.reset_mock()
            app.sync_state["services"] = [{"name": "tracked-service", "hostname": "tracked.example.com"}]
            app.handle_docker_event(
                {"Type": "container", "Action": "die", "Actor": {"Attributes": {"name": "tracked-service"}}}
            )
            mock_trigger.assert_called_with("die:tracked-service")

            # 8. Image pull event -> must be ignored
            mock_trigger.reset_mock()
            app.handle_docker_event({"Type": "image", "Action": "pull", "id": "sha256:abc"})
            mock_trigger.assert_not_called()

            # 9. Non-lifecycle container action (e.g. top) -> must be ignored
            mock_trigger.reset_mock()
            app.handle_docker_event({"Type": "container", "Action": "top"})
            mock_trigger.assert_not_called()

    def test_handle_docker_event_unlabeled_filtering_can_be_disabled(self):
        """Verify FILTER_UNLABELED_EVENTS=false allows all container lifecycle events through."""
        from tunnel_sync.configuration.settings import Settings
        from tunnel_sync.runtime.scheduler import Scheduler

        mock_trigger = MagicMock()
        scheduler = Scheduler(
            Settings({"FILTER_UNLABELED_EVENTS": "false"}),
            run_once=MagicMock(),
            events=MagicMock(),
            log=MagicMock(),
        )
        scheduler.debouncer.trigger = mock_trigger

        scheduler.handle_event(
            {"Type": "container", "Action": "start", "Actor": {"Attributes": {"name": "unlabelled-container"}}}
        )
        mock_trigger.assert_called_with("start:unlabelled-container")

    @patch("os.path.exists", return_value=True)
    @patch("app.UnixHTTPConnection")
    def test_listen_docker_events_stream_and_eof(self, mock_conn_cls, mock_exists):
        """Verify listen_docker_events streams events and terminates cleanly on stop_event."""
        events_received = []
        stop_event = threading.Event()

        mock_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 200

        # Simulate chunked lines received from Docker socket
        payloads = [
            b'{"Type": "container", "Action": "start", "Actor": {"Attributes": {"name": "c1"}}}\n',
            b'{"Type": "container", "Action": "die", "Actor": {"Attributes": {"name": "c2"}}}\n',
            b"",  # EOF
        ]
        mock_resp.read.side_effect = payloads
        mock_conn.getresponse.return_value = mock_resp
        mock_conn_cls.return_value = mock_conn

        def callback(evt):
            events_received.append(evt)
            if len(events_received) >= 2:
                stop_event.set()

        # Run listener in background thread with stop_event
        t = threading.Thread(
            target=app.listen_docker_events, args=(callback, stop_event, "/var/run/docker.sock"), daemon=True
        )
        t.start()
        t.join(timeout=2.0)

        self.assertEqual(len(events_received), 2)
        self.assertEqual(events_received[0]["Action"], "start")
        self.assertEqual(events_received[1]["Action"], "die")
        self.assertTrue(app.sync_state["docker_connected"])

    async def test_debouncer_coalesces_without_task_churn(self):
        """Verify debouncer coalesces rapid events into a single worker task without churn."""
        mock_sync = MagicMock()
        debouncer = app.DebouncedSyncTrigger(delay=0.10, max_delay=0.5, sync_target=mock_sync)
        loop = asyncio.get_running_loop()
        debouncer.set_loop(loop)

        # Fire 20 rapid bursts within 20ms
        for i in range(20):
            debouncer.trigger(f"event_{i}")
            await asyncio.sleep(0.001)

        worker = debouncer._worker_task
        self.assertIsNotNone(worker)
        self.assertFalse(worker.done())

        # Wait for debounce delay to expire
        await asyncio.sleep(0.15)

        self.assertEqual(mock_sync.call_count, 1)
        self.assertIsNone(debouncer._deadline)
        self.assertIsNone(debouncer._max_deadline)

    @patch("os.path.exists", return_value=True)
    @patch("app.UnixHTTPConnection")
    def test_listen_docker_events_buffered_partial_chunks(self, mock_conn_cls, mock_exists):
        """Verify buffered reader handles events split across chunk boundaries."""
        mock_conn = MagicMock()
        mock_conn_cls.return_value = mock_conn
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_conn.getresponse.return_value = mock_resp

        # Event split across two chunks + empty lines
        payloads = [
            b'\n\n{"Type": "container", "Action": "start", "Actor": {',
            b'"Attributes": {"name": "stream-worker"}}}\n\n',
            b"",
        ]
        mock_resp.read.side_effect = payloads

        events_received = []
        stop_event = threading.Event()

        def callback(evt):
            events_received.append(evt)
            stop_event.set()

        t = threading.Thread(
            target=app.listen_docker_events, args=(callback, stop_event, "/var/run/docker.sock"), daemon=True
        )
        t.start()
        t.join(timeout=2.0)

        self.assertEqual(len(events_received), 1)
        self.assertEqual(events_received[0]["Action"], "start")
        self.assertEqual(events_received[0]["Actor"]["Attributes"]["name"], "stream-worker")


if __name__ == "__main__":
    unittest.main()
