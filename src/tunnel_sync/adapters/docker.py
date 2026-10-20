"""Docker Unix/TCP requests and bounded event streaming."""

import http.client
import json
import os
import socket
import threading
import time
import urllib.parse
from typing import Any, Callable, Optional

from tunnel_sync.application.inventory import InventoryUnavailableError
from tunnel_sync.configuration.settings import Settings


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: Optional[float] = 10.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path
        self.timeout = timeout

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if self.timeout is not None:
            self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


class DockerAPIError(Exception):
    """Raised when the Docker API returns an HTTP error status code or malformed payload."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class DockerUnavailableError(DockerAPIError, InventoryUnavailableError):
    """No trustworthy inventory was received; distinct from a successful empty list."""


class DockerReadAdapter:
    """Inventory/preflight capability; mutating requests are rejected locally."""

    def __init__(self, request):
        self._request = request

    def request(self, path, method="GET", **kwargs):
        if method != "GET":
            raise ValueError("Docker reader only supports GET")
        return self._request(path, method=method, **kwargs)


class DockerClient:
    def __init__(
        self,
        settings: Settings,
        report_connection: Callable[[bool], None],
        log: Callable[[str], None],
        unix_connection=UnixHTTPConnection,
    ):
        self.settings = settings
        self.report_connection = report_connection
        self.log = log
        self.unix_connection = unix_connection
        self._event_connection: http.client.HTTPConnection | None = None
        self._event_lock = threading.Lock()

    def close_events(self):
        with self._event_lock:
            connection = self._event_connection
            self._event_connection = None
        if connection is not None:
            sock = getattr(connection, "sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            connection.close()

    def request(
        self,
        path: str,
        method: str = "GET",
        data: dict | None = None,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
    ) -> Any:
        docker_host = self.settings.get("DOCKER_HOST", "").strip()
        is_tcp = docker_host.startswith("tcp://") or docker_host.startswith("http://")
        socket_path = self.settings.get(
            "DOCKER_SOCKET", self.settings.get("DOCKER_SOCKET_PATH", "/var/run/docker.sock")
        )

        if not is_tcp and not os.path.exists(socket_path):
            self.report_connection(False)
            raise DockerUnavailableError(f"Docker socket not found at {socket_path}")

        if timeout is None:
            try:
                timeout = float(self.settings.get("DOCKER_TIMEOUT", 10.0))
            except ValueError:
                timeout = 10.0

        if retries is None:
            try:
                retries = int(self.settings.get("DOCKER_RETRIES", 3))
            except ValueError:
                retries = 3

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            conn = None
            try:
                if is_tcp:
                    parsed = urllib.parse.urlparse(docker_host)
                    host = parsed.hostname or "localhost"
                    port = parsed.port or 2375
                    conn = http.client.HTTPConnection(host, port, timeout=timeout)
                else:
                    conn = self.unix_connection(socket_path, timeout=timeout)
                body = None
                headers = {}
                if data is not None:
                    body = json.dumps(data).encode("utf-8")
                    headers["Content-Type"] = "application/json"
                    headers["Content-Length"] = str(len(body))

                conn.request(method, path, body=body, headers=headers)
                resp = conn.getresponse()

                resp_status = getattr(resp, "status", 200)
                if isinstance(resp_status, str) and resp_status.isdigit():
                    resp_status = int(resp_status)
                elif not isinstance(resp_status, int):
                    resp_status = 200

                resp_data = resp.read().decode("utf-8")

                if resp_status < 200 or resp_status >= 300:
                    self.report_connection(False)
                    err_msg = f"Docker API HTTP {resp_status} on {method} {path}: {resp_data}"
                    self.log(err_msg)
                    raise DockerAPIError(err_msg, status_code=resp_status)

                if resp_data:
                    try:
                        parsed = json.loads(resp_data)
                    except Exception as je:
                        self.report_connection(False)
                        err_msg = f"Docker API returned invalid JSON on {method} {path}: {je}"
                        self.log(err_msg)
                        raise DockerAPIError(err_msg, status_code=resp_status)
                    self.report_connection(True)
                    return parsed

                self.report_connection(True)
                return {}
            except DockerAPIError:
                raise
            except (socket.timeout, TimeoutError) as e:
                last_error = e
                self.report_connection(False)
                self.log(f"Docker API timeout on {path} (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    time.sleep(0.1 * (2 ** (attempt - 1)))
            except (socket.error, http.client.HTTPException, ConnectionError, OSError) as e:
                last_error = e
                self.report_connection(False)
                self.log(f"Docker API error on {path} (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    time.sleep(0.1 * (2 ** (attempt - 1)))
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        self.report_connection(False)
        self.log(f"Docker API failed after {retries} retries: {last_error}")
        raise DockerUnavailableError(f"Docker API failed after {retries} retries: {last_error}")

    def listen_events(
        self,
        on_event: Callable[[dict], None],
        stop_event: Optional[threading.Event] = None,
        socket_path: Optional[str] = None,
    ):
        docker_host = self.settings.get("DOCKER_HOST", "").strip()
        is_tcp = docker_host.startswith("tcp://") or docker_host.startswith("http://")
        if socket_path is None:
            socket_path = self.settings.get(
                "DOCKER_SOCKET", self.settings.get("DOCKER_SOCKET_PATH", "/var/run/docker.sock")
            )

        backoff = 1.0
        max_backoff = 30.0

        while stop_event is None or not stop_event.is_set():
            if not is_tcp and not os.path.exists(socket_path):
                self.report_connection(False)
                self.log(f"Docker socket not found at {socket_path}, retrying in {backoff:.1f}s")
                if stop_event:
                    if stop_event.wait(backoff):
                        break
                else:
                    time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue

            conn = None
            try:
                if is_tcp:
                    parsed = urllib.parse.urlparse(docker_host)
                    host = parsed.hostname or "localhost"
                    port = parsed.port or 2375
                    conn = http.client.HTTPConnection(host, port, timeout=10.0)
                else:
                    conn = self.unix_connection(socket_path, timeout=10.0)
                with self._event_lock:
                    self._event_connection = conn
                if stop_event is not None and stop_event.is_set():
                    break
                query = "/events?filters=%7B%22type%22%3A%5B%22container%22%5D%7D"
                conn.request("GET", query)
                resp = conn.getresponse()

                if getattr(conn, "sock", None) is not None:
                    conn.sock.settimeout(None)

                if resp.status != 200:
                    self.report_connection(False)
                    self.log(f"Docker /events returned HTTP {resp.status}, retrying in {backoff:.1f}s")
                    if stop_event:
                        if stop_event.wait(backoff):
                            break
                    else:
                        time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                    continue

                self.report_connection(True)
                backoff = 1.0
                self.log("Connected to Docker /events stream")

                buffer = bytearray()
                while stop_event is None or not stop_event.is_set():
                    chunk = resp.read(4096)
                    if not chunk:
                        self.log("Docker /events stream closed by daemon (EOF)")
                        break
                    buffer.extend(chunk)
                    while True:
                        newline_idx = buffer.find(b"\n")
                        if newline_idx == -1:
                            break
                        line = buffer[:newline_idx].strip()
                        del buffer[: newline_idx + 1]
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                            if on_event is not None:
                                on_event(parsed)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            pass
            except Exception as e:
                self.report_connection(False)
                self.log(f"Docker /events stream error: {e}")
                if stop_event:
                    if stop_event.wait(backoff):
                        break
                else:
                    time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            finally:
                with self._event_lock:
                    if self._event_connection is conn:
                        self._event_connection = None
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
