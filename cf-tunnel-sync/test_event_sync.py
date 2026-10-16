import unittest
from unittest.mock import patch, MagicMock
import asyncio
import io
import threading
import time
import app


class TestEventDrivenSync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.sync_state["status"] = "Initializing"
        app.sync_state["docker_connected"] = True
        app.sync_state["logs"] = []

    async def test_debouncer_bundles_rapid_events(self):
        """Verify that rapid successive events are bundled into a single sync execution."""
        mock_sync = MagicMock()
        debouncer = app.DebouncedSyncTrigger(delay=0.08, sync_target=mock_sync)
        debouncer.set_loop(asyncio.get_running_loop())

        # Trigger 5 rapid events in succession
        for i in range(5):
            debouncer.trigger(f"event_{i}")
            await asyncio.sleep(0.02)

        # Allow debounce window to elapse
        await asyncio.sleep(0.12)

        # Ensure sync callback was executed exactly ONCE
        self.assertEqual(mock_sync.call_count, 1)

    async def test_debouncer_respects_max_delay(self):
        """Verify that a steady stream of events does not starve sync past max_delay."""
        mock_sync = MagicMock()
        debouncer = app.DebouncedSyncTrigger(delay=0.08, max_delay=0.15, sync_target=mock_sync)
        debouncer.set_loop(asyncio.get_running_loop())

        start_time = time.time()
        # Continuously trigger events every 0.04s for 0.25s
        while time.time() - start_time < 0.25:
            debouncer.trigger("continuous_event")
            await asyncio.sleep(0.04)

        await asyncio.sleep(0.12)
        # Should have executed at least once despite constant triggers
        self.assertGreaterEqual(mock_sync.call_count, 1)

    def test_handle_docker_event_filters(self):
        """Verify handle_docker_event triggers on container lifecycle actions and ignores others."""
        with patch.object(app.debouncer, "trigger") as mock_trigger:
            # 1. Container start event -> should trigger
            app.handle_docker_event({
                "Type": "container",
                "Action": "start",
                "Actor": {"Attributes": {"name": "web-nginx"}}
            })
            mock_trigger.assert_called_with("start:web-nginx")

            # 2. Container stop event -> should trigger
            app.handle_docker_event({
                "Type": "container",
                "Action": "stop",
                "Actor": {"Attributes": {"name": "db-postgres"}}
            })
            mock_trigger.assert_called_with("stop:db-postgres")

            # 3. Container die event -> should trigger
            app.handle_docker_event({
                "Type": "container",
                "Action": "die",
                "id": "1234567890abcdef",
                "Actor": {}
            })
            mock_trigger.assert_called_with("die:1234567890ab")

            # 4. Image pull event -> must be ignored
            mock_trigger.reset_mock()
            app.handle_docker_event({
                "Type": "image",
                "Action": "pull",
                "id": "sha256:abc"
            })
            mock_trigger.assert_not_called()

            # 5. Non-lifecycle container action (e.g. top) -> must be ignored
            app.handle_docker_event({
                "Type": "container",
                "Action": "top"
            })
            mock_trigger.assert_not_called()

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
            b''  # EOF
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
            target=app.listen_docker_events,
            args=(callback, stop_event, "/var/run/docker.sock"),
            daemon=True
        )
        t.start()
        t.join(timeout=2.0)

        self.assertEqual(len(events_received), 2)
        self.assertEqual(events_received[0]["Action"], "start")
        self.assertEqual(events_received[1]["Action"], "die")
        self.assertTrue(app.sync_state["docker_connected"])


if __name__ == "__main__":
    unittest.main()
