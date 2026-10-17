import asyncio
import http.client
import json
import logging
import os
import re
import secrets
import socket
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, List, Optional

import uvicorn
from cloudflare import cf_api
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cf-tunnel-sync")
logger.setLevel(LOG_LEVEL)


class HealthCheckFilter(logging.Filter):
    """Filter to suppress /health access logs unless LOG_LEVEL is DEBUG."""

    def filter(self, record: logging.LogRecord) -> bool:
        if os.getenv("LOG_LEVEL", "INFO").upper() == "DEBUG":
            return True
        try:
            if record.args and len(record.args) >= 3:
                req_path = str(record.args[2])
                if req_path == "/health" or req_path.startswith("/health?"):
                    return False
            msg = record.getMessage()
            if " /health " in msg or " /health?" in msg or '"/health"' in msg or '"/health ' in msg:
                return False
        except Exception:
            pass
        return True


logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())


LABEL_REGEX = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_hostname(hostname: Optional[str]) -> Optional[str]:
    """Normalize and validate a hostname string according to RFC 1123.

    Strips scheme, trailing path, query/fragments, authentication, ports,
    and trailing dots. Lowercases all characters and ensures every DNS label
    satisfies RFC 1123 length and character restrictions.
    Returns None if the hostname is invalid or empty.
    """
    if not hostname or not isinstance(hostname, str):
        return None
    raw = hostname.strip()
    if not raw:
        return None
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if "?" in raw:
        raw = raw.split("?", 1)[0]
    if "#" in raw:
        raw = raw.split("#", 1)[0]
    if "@" in raw:
        raw = raw.split("@", 1)[1]
    if ":" in raw and not raw.startswith("["):
        raw = raw.split(":", 1)[0]
    raw = raw.strip().rstrip(".").lower()
    if not raw or len(raw) > 253:
        return None
    labels = raw.split(".")
    for i, label in enumerate(labels):
        if not label or len(label) > 63:
            return None
        if label == "*":
            if i != 0 or len(labels) < 2:
                return None
            continue
        if not LABEL_REGEX.match(label):
            return None
    return raw


def get_domain_name() -> str:
    return os.getenv("DOMAIN_NAME", "").strip().rstrip(".").lower()


sync_lock = threading.Lock()

sync_state = {
    "last_sync": None,
    "status": "Initializing",
    "tunnel_id": None,
    "tunnel_name": os.getenv("CLOUDFLARE_TUNNEL_NAME", "cf-docker-tunnel-sync").strip(),
    "domain_name": get_domain_name(),
    "discovered_services": [],
    "all_containers": [],
    "dns_records": [],
    "logs": [],
    "docker_connected": True,
    "tombstones": {},
}


def add_log(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    logger.info(msg)
    sync_state["logs"].insert(0, entry)
    if len(sync_state["logs"]) > 100:
        sync_state["logs"].pop()


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


def docker_api(
    path: str, method: str = "GET", data: dict = None, timeout: Optional[float] = None, retries: Optional[int] = None
) -> Any:
    socket_path = os.getenv("DOCKER_SOCKET", os.getenv("DOCKER_SOCKET_PATH", "/var/run/docker.sock"))
    if not os.path.exists(socket_path):
        sync_state["docker_connected"] = False
        return []

    if timeout is None:
        try:
            timeout = float(os.getenv("DOCKER_TIMEOUT", 10.0))
        except ValueError:
            timeout = 10.0

    if retries is None:
        try:
            retries = int(os.getenv("DOCKER_RETRIES", 3))
        except ValueError:
            retries = 3

    last_error = None
    for attempt in range(1, retries + 1):
        conn = None
        try:
            conn = UnixHTTPConnection(socket_path, timeout=timeout)
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
                sync_state["docker_connected"] = False
                err_msg = f"Docker API HTTP {resp_status} on {method} {path}: {resp_data}"
                add_log(err_msg)
                raise DockerAPIError(err_msg, status_code=resp_status)

            if resp_data:
                try:
                    parsed = json.loads(resp_data)
                except Exception as je:
                    sync_state["docker_connected"] = False
                    err_msg = f"Docker API returned invalid JSON on {method} {path}: {je}"
                    add_log(err_msg)
                    raise DockerAPIError(err_msg, status_code=resp_status)
                sync_state["docker_connected"] = True
                return parsed

            sync_state["docker_connected"] = True
            return {}
        except DockerAPIError:
            raise
        except (socket.timeout, TimeoutError) as e:
            last_error = e
            sync_state["docker_connected"] = False
            add_log(f"Docker API timeout on {path} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(0.1 * (2 ** (attempt - 1)))
        except (socket.error, http.client.HTTPException, ConnectionError, OSError) as e:
            last_error = e
            sync_state["docker_connected"] = False
            add_log(f"Docker API error on {path} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(0.1 * (2 ** (attempt - 1)))
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    sync_state["docker_connected"] = False
    add_log(f"Docker API failed after {retries} retries: {last_error}")
    return []


# Event-driven Debouncer & Stream Listener
CONTAINER_LIFECYCLE_ACTIONS = {"start", "stop", "die", "kill", "destroy", "rename", "pause", "unpause", "restart"}


class DebouncedSyncTrigger:
    def __init__(self, delay: float = 2.5, max_delay: float = 10.0, sync_target: Optional[Callable] = None):
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
                    pass

            if target_loop and target_loop.is_running():
                target_loop.call_soon_threadsafe(self._ensure_worker)

    def _ensure_worker(self):
        with self._lock:
            if self._worker_task is None or self._worker_task.done():
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
            add_log(f"Debounce window elapsed ({self.delay}s), executing sync: {reason_str}")
            try:
                if self.sync_target:
                    if asyncio.iscoroutinefunction(self.sync_target):
                        await self.sync_target()
                    else:
                        await asyncio.to_thread(self.sync_target)
                else:
                    await asyncio.to_thread(run_sync_logic)
            except Exception as e:
                logger.error(f"Error during debounced sync: {e}")


DEBOUNCE_DELAY = float(os.getenv("SYNC_DEBOUNCE_SECONDS", os.getenv("SYNC_DEBOUNCE_DELAY", 2.5)))
DEBOUNCE_MAX_DELAY = float(os.getenv("SYNC_DEBOUNCE_MAX_DELAY", 10.0))
debouncer = DebouncedSyncTrigger(delay=DEBOUNCE_DELAY, max_delay=DEBOUNCE_MAX_DELAY)


def handle_docker_event(event: dict):
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
        add_log(f"Container lifecycle event: {base_action} for {container_name}")
        debouncer.trigger(f"{base_action}:{container_name}")


def listen_docker_events(
    on_event: Callable[[dict], None], stop_event: Optional[threading.Event] = None, socket_path: Optional[str] = None
):
    if socket_path is None:
        socket_path = os.getenv("DOCKER_SOCKET", os.getenv("DOCKER_SOCKET_PATH", "/var/run/docker.sock"))

    backoff = 1.0
    max_backoff = 30.0

    while stop_event is None or not stop_event.is_set():
        if not os.path.exists(socket_path):
            sync_state["docker_connected"] = False
            add_log(f"Docker socket not found at {socket_path}, retrying in {backoff:.1f}s")
            if stop_event:
                if stop_event.wait(backoff):
                    break
            else:
                time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            continue

        conn = None
        try:
            conn = UnixHTTPConnection(socket_path, timeout=None)
            query = "/events?filters=%7B%22type%22%3A%5B%22container%22%5D%7D"
            conn.request("GET", query)
            resp = conn.getresponse()

            if resp.status != 200:
                sync_state["docker_connected"] = False
                add_log(f"Docker /events returned HTTP {resp.status}, retrying in {backoff:.1f}s")
                if stop_event:
                    if stop_event.wait(backoff):
                        break
                else:
                    time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue

            sync_state["docker_connected"] = True
            backoff = 1.0
            add_log("Connected to Docker /events stream")

            buffer = bytearray()
            while stop_event is None or not stop_event.is_set():
                chunk = resp.read(4096)
                if not chunk:
                    add_log("Docker /events stream closed by daemon (EOF)")
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
                        if on_event:
                            on_event(parsed)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
        except Exception as e:
            sync_state["docker_connected"] = False
            add_log(f"Docker /events stream error: {e}")
            if stop_event:
                if stop_event.wait(backoff):
                    break
            else:
                time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


def find_cloudflared_container_name() -> str:
    """Resolve the cloudflared container name or ID dynamically."""
    explicit_name = os.getenv("CLOUDFLARED_CONTAINER_NAME", "").strip()
    if explicit_name:
        return explicit_name

    try:
        containers = docker_api("/containers/json?all=true")
        if isinstance(containers, list):
            my_hostname = os.getenv("HOSTNAME", "").strip()
            current_project = None
            if my_hostname:
                for c in containers:
                    c_id = c.get("Id", "")
                    c_names = [n.lstrip("/") for n in c.get("Names", [])]
                    if c_id.startswith(my_hostname) or my_hostname in c_names:
                        current_project = (c.get("Labels") or {}).get("com.docker.compose.project")
                        break

            for c in containers:
                labels = c.get("Labels") or {}
                service = labels.get("com.docker.compose.service")
                project = labels.get("com.docker.compose.project")
                if service == "cloudflared":
                    if current_project and project == current_project:
                        c_names = c.get("Names", [])
                        if c_names:
                            return c_names[0].lstrip("/")
                        return c.get("Id", "cloudflared")
                    elif not current_project:
                        c_names = c.get("Names", [])
                        if c_names:
                            return c_names[0].lstrip("/")
                        return c.get("Id", "cloudflared")
    except Exception as e:
        logger.warning(f"Error resolving cloudflared container: {e}")

    return "cloudflared"


def get_docker_containers() -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    services = []
    all_containers = []
    seen_hostnames = set()
    configured_domain = get_domain_name().lower()
    configured_tunnel_name = os.getenv("CLOUDFLARE_TUNNEL_NAME", "cf-docker-tunnel-sync").strip()

    try:
        expected_network = os.getenv("CF_NETWORK_NAME", "cf-tunnel-net").strip()
        require_shared_net = os.getenv("REQUIRE_SHARED_NETWORK", "false").lower() in ("true", "1", "yes")

        cloudflared_networks = set()
        if expected_network:
            cloudflared_networks.add(expected_network)

        LEGACY_LABEL_CANONICAL_MAP = {
            "cloudflared.hostname": "cf.tunnel.hostname",
            "cloudflared.domain": "cf.tunnel.domain",
            "cloudflared.port": "cf.tunnel.port",
            "cloudflared.service": "cf.tunnel.service",
            "cloudflared.proto": "cf.tunnel.proto",
            "cloudflared.protocol": "cf.tunnel.protocol",
            "cloudflared.scheme": "cf.tunnel.scheme",
            "cloudflared.name": "cf.tunnel.name",
            "cloudflared.tunnel": "cf.tunnel.name",
            "cloudflared.notlsverify": "cf.tunnel.origin_request.no_tls_verify",
            "cloudflared.notls_verify": "cf.tunnel.origin_request.no_tls_verify",
            "cloudflared.originRequest.noTLSVerify": "cf.tunnel.origin_request.no_tls_verify",
            "cloudflared.origin_request.no_tls_verify": "cf.tunnel.origin_request.no_tls_verify",
            "cloudflared.httpHostHeader": "cf.tunnel.origin_request.http_host_header",
            "cloudflared.originRequest.httpHostHeader": "cf.tunnel.origin_request.http_host_header",
            "port": "cf.tunnel.port",
            "proto": "cf.tunnel.proto",
            "protocol": "cf.tunnel.protocol",
            "scheme": "cf.tunnel.scheme",
            "notlsverify": "cf.tunnel.origin_request.no_tls_verify",
            "cloudflared.host": "cf.tunnel.hostname",
            "cf.tunnel.host": "cf.tunnel.hostname",
            "hostname": "cf.tunnel.hostname",
            "host": "cf.tunnel.hostname",
        }

        containers = docker_api("/containers/json?all=true")
        if not isinstance(containers, list):
            sync_state["docker_connected"] = False
            add_log("Docker API container discovery returned non-list response; failing closed")
            return [], []

        if containers:
            sync_state["docker_connected"] = True
        elif not sync_state.get("docker_connected", True):
            return [], []

        if isinstance(containers, list):
            cf_target_name = find_cloudflared_container_name()
            for cand in containers:
                if isinstance(cand, dict):
                    cand_labels = cand.get("Labels") or {}
                    cand_names = cand.get("Names", [])
                    cand_name_clean = cand_names[0].lstrip("/") if cand_names else ""
                    if (
                        cand_labels.get("com.docker.compose.service") == "cloudflared"
                        or cand_name_clean == cf_target_name
                    ):
                        cand_nets = (cand.get("NetworkSettings") or {}).get("Networks") or {}
                        cloudflared_networks.update(cand_nets.keys())
            for c in containers:
                labels = c.get("Labels") or {}
                c_names = c.get("Names", ["/unknown"])
                c_name = c_names[0].lstrip("/") if c_names else "unknown"
                for leg_key, canonical in LEGACY_LABEL_CANONICAL_MAP.items():
                    if leg_key in labels:
                        warn_key = (c_name, leg_key)
                        if warn_key not in sync_state.setdefault("_deprecations_warned", set()):
                            sync_state["_deprecations_warned"].add(warn_key)
                            add_log(
                                f"⚠️ Deprecation Notice: Container '{c_name}' uses legacy alias '{leg_key}'. Please migrate to canonical '{canonical}'."
                            )
                state = c.get("State", "unknown")
                status_text = c.get("Status", "")
                image = c.get("Image", "")

                raw_hostname = (
                    labels.get("cf.tunnel.hostname")
                    or labels.get("cf.tunnel.domain")
                    or labels.get("cf.tunnel.host")
                    or labels.get("cloudflared.hostname")
                    or labels.get("cloudflared.domain")
                    or labels.get("cloudflared.host")
                    or labels.get("hostname")
                    or labels.get("host")
                )

                hostname = ""
                if raw_hostname:
                    normalized = normalize_hostname(str(raw_hostname))
                    if not normalized:
                        add_log(
                            f"⚠️ Invalid hostname '{raw_hostname}' for container '{c_name}' rejected (must be valid RFC 1123)"
                        )
                    else:
                        hostname = normalized

                # Domain scoping: only match if hostname belongs to configured DOMAIN_NAME
                matches_domain = True
                if configured_domain and hostname:
                    matches_domain = (hostname == configured_domain) or (hostname.endswith("." + configured_domain))

                # Optional tunnel scoping: if cf.tunnel.name is set, verify it matches CLOUDFLARE_TUNNEL_NAME
                target_tunnel = (
                    labels.get("cf.tunnel.name")
                    or labels.get("cf.tunnel.tunnel")
                    or labels.get("cloudflared.name")
                    or labels.get("cloudflared.tunnel")
                )
                matches_tunnel = True
                if target_tunnel:
                    matches_tunnel = str(target_tunnel).strip() == configured_tunnel_name

                is_tunneled = False
                service_url = ""

                if hostname and state == "running" and matches_domain and matches_tunnel:
                    if hostname in seen_hostnames:
                        add_log(f"⚠️ Duplicate hostname '{hostname}' for container '{c_name}' ignored")
                    else:
                        seen_hostnames.add(hostname)
                        is_tunneled = True

                        # Protocol / Scheme (precedence: modern cf.tunnel.* > legacy cloudflared.* > bare shorthand)
                        raw_proto = (
                            labels.get("cf.tunnel.protocol")
                            or labels.get("cf.tunnel.proto")
                            or labels.get("cf.tunnel.scheme")
                            or labels.get("cloudflared.protocol")
                            or labels.get("cloudflared.proto")
                            or labels.get("cloudflared.scheme")
                            or labels.get("proto")
                            or labels.get("protocol")
                            or labels.get("scheme")
                            or "http"
                        )
                        proto = str(raw_proto).strip().lower()
                        if proto not in ("http", "https", "tcp", "udp", "ssh", "rdp"):
                            proto = "http"

                        # Port parsing and validation (precedence: modern > legacy > bare shorthand)
                        port_label = (
                            labels.get("cf.tunnel.port") or labels.get("cloudflared.port") or labels.get("port")
                        )
                        valid_port = None
                        if port_label:
                            port_str = str(port_label).strip()
                            if port_str.isdigit():
                                p_int = int(port_str)
                                if 1 <= p_int <= 65535:
                                    valid_port = p_int
                                else:
                                    add_log(f"⚠️ Port {p_int} for container '{c_name}' out of range (1-65535)")
                            else:
                                add_log(f"⚠️ Non-numeric port '{port_label}' for container '{c_name}'")

                        # Service URL assembly (precedence: modern > legacy)
                        explicit_service = labels.get("cf.tunnel.service") or labels.get("cloudflared.service")
                        if explicit_service and str(explicit_service).strip():
                            service_url = str(explicit_service).strip()
                        elif valid_port is not None:
                            service_url = f"{proto}://{c_name}:{valid_port}"
                        else:
                            ports = c.get("Ports", [])
                            inspected_port = None
                            if isinstance(ports, list) and ports and isinstance(ports[0], dict):
                                ip = ports[0].get("PrivatePort")
                                if isinstance(ip, int) and 1 <= ip <= 65535:
                                    inspected_port = ip
                            if inspected_port:
                                service_url = f"{proto}://{c_name}:{inspected_port}"
                            else:
                                default_port = 443 if proto == "https" else 80
                                service_url = f"{proto}://{c_name}:{default_port}"

                        # Origin request & TLS settings
                        origin_request = {}
                        no_tls_verify = False

                        def _parse_bool(v):
                            if v is None:
                                return None
                            s = str(v).strip().lower()
                            if s in ("true", "1", "yes"):
                                return True
                            if s in ("false", "0", "no"):
                                return False
                            return None

                        # Precedence: modern cf.tunnel.* > legacy cloudflared.* > bare shorthand
                        modern_notls = _parse_bool(
                            labels.get("cf.tunnel.notlsverify")
                            or labels.get("cf.tunnel.notls_verify")
                            or labels.get("cf.tunnel.originRequest.noTLSVerify")
                            or labels.get("cf.tunnel.origin_request.no_tls_verify")
                        )
                        modern_tls = _parse_bool(
                            labels.get("cf.tunnel.tls.verify") or labels.get("cf.tunnel.tls_verify")
                        )

                        legacy_notls = _parse_bool(
                            labels.get("cloudflared.notlsverify")
                            or labels.get("cloudflared.notls_verify")
                            or labels.get("cloudflared.originRequest.noTLSVerify")
                            or labels.get("cloudflared.origin_request.no_tls_verify")
                        )
                        legacy_tls = _parse_bool(
                            labels.get("cloudflared.tls.verify") or labels.get("cloudflared.tls_verify")
                        )

                        shorthand_notls = _parse_bool(labels.get("notlsverify") or labels.get("no_tls_verify"))
                        shorthand_tls = _parse_bool(labels.get("tls_verify"))

                        if modern_notls is not None:
                            no_tls_verify = modern_notls
                        elif modern_tls is not None:
                            no_tls_verify = not modern_tls
                        elif legacy_notls is not None:
                            no_tls_verify = legacy_notls
                        elif legacy_tls is not None:
                            no_tls_verify = not legacy_tls
                        elif shorthand_notls is not None:
                            no_tls_verify = shorthand_notls
                        elif shorthand_tls is not None:
                            no_tls_verify = not shorthand_tls
                        else:
                            no_tls_verify = False

                        if no_tls_verify:
                            origin_request["noTLSVerify"] = True

                        # Origin Server Name override (modern > legacy)
                        origin_server_name = (
                            labels.get("cf.tunnel.originServerName")
                            or labels.get("cf.tunnel.origin.server.name")
                            or labels.get("cf.tunnel.origin_server_name")
                            or labels.get("cloudflared.originServerName")
                            or labels.get("cloudflared.origin.server.name")
                            or labels.get("cloudflared.origin_server_name")
                        )
                        if origin_server_name and str(origin_server_name).strip():
                            origin_request["originServerName"] = str(origin_server_name).strip()

                        # HTTP host header override (modern > legacy)
                        http_host_header = (
                            labels.get("cf.tunnel.httpHostHeader")
                            or labels.get("cf.tunnel.http.host.header")
                            or labels.get("cf.tunnel.http_host_header")
                            or labels.get("cloudflared.httpHostHeader")
                            or labels.get("cloudflared.http.host.header")
                            or labels.get("cloudflared.http_host_header")
                        )
                        if http_host_header and str(http_host_header).strip():
                            origin_request["httpHostHeader"] = str(http_host_header).strip()

                        # Network Pre-flight Diagnostic
                        c_nets = (c.get("NetworkSettings") or {}).get("Networks") or {}
                        container_networks = set(c_nets.keys())
                        if container_networks and cloudflared_networks:
                            has_shared_net = bool(container_networks.intersection(cloudflared_networks))
                        else:
                            has_shared_net = True

                        if not has_shared_net:
                            add_log(
                                f"⚠️ Network Diagnostic: Container '{c_name}' is not attached to Cloudflare tunnel network '{expected_network}'. Requests to '{service_url}' will fail with 502 Bad Gateway!"
                            )
                            if require_shared_net:
                                add_log(
                                    f"⛔ Excluding '{c_name}' from sync: REQUIRE_SHARED_NETWORK=true and shared network '{expected_network}' is missing."
                                )
                                is_tunneled = False

                        service_item = {
                            "container": c_name,
                            "hostname": hostname,
                            "service": service_url,
                            "no_tls_verify": no_tls_verify,
                            "network_connected": has_shared_net,
                        }
                        if not has_shared_net:
                            service_item["network_warning"] = f"Missing shared network '{expected_network}'"
                        if origin_request:
                            service_item["originRequest"] = origin_request

                        if is_tunneled:
                            services.append(service_item)

                all_containers.append(
                    {
                        "name": c_name,
                        "image": image,
                        "state": state,
                        "status": status_text,
                        "hostname": hostname if hostname else "-",
                        "is_tunneled": is_tunneled,
                        "network_connected": has_shared_net if "has_shared_net" in locals() else True,
                    }
                )
    except Exception as e:
        sync_state["docker_connected"] = False
        add_log(f"Docker API Error: {e}")
        return [], []
    return services, all_containers


def build_ingress_rules(services: list) -> list:
    """
    Constructs deterministic Cloudflare Tunnel ingress rules from discovered services.
    Appends the mandatory catch-all 404 rule at the end.
    """
    rules = []
    # Deterministic alphabetical sorting by hostname to prevent spurious configuration updates
    sorted_services = sorted(
        services,
        key=lambda s: normalize_hostname(s.get("hostname", "")) or s.get("hostname", ""),
    )

    for s in sorted_services:
        raw_host = s.get("hostname")
        service_target = s.get("service")
        if not raw_host or not service_target:
            continue

        hostname = normalize_hostname(raw_host)
        if not hostname:
            continue

        rule = {
            "hostname": hostname,
            "service": service_target,
        }

        origin_req = dict(s.get("originRequest", {}))
        if s.get("no_tls_verify") or s.get("noTLSVerify"):
            origin_req["noTLSVerify"] = True

        if origin_req:
            rule["originRequest"] = origin_req

        rules.append(rule)

    rules.append({"service": "http_status:404"})
    return rules


def run_sync_logic():
    if not sync_lock.acquire(blocking=False):
        add_log("⏳ Sync already in progress, skipping concurrent run")
        return

    try:
        token = os.getenv("CLOUDFLARE_API_TOKEN")
        domain = get_domain_name()
        tunnel_name = os.getenv("CLOUDFLARE_TUNNEL_NAME", "cf-docker-tunnel-sync").strip()
        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        if account_id:
            account_id = account_id.strip()

        sync_state["status"] = "Syncing..."
        sync_state["domain_name"] = domain
        sync_state["tunnel_name"] = tunnel_name

        if not token or token == "your_cloudflare_api_token_here":
            sync_state["status"] = "Waiting for CLOUDFLARE_API_TOKEN in .env"
            add_log("⚠️ CLOUDFLARE_API_TOKEN missing or default placeholder in .env!")
            return

        if not domain or domain == "yourdomain.com":
            sync_state["status"] = "Waiting for DOMAIN_NAME in .env"
            add_log("⚠️ DOMAIN_NAME missing or default placeholder in .env!")
            return

        # 1. Resolve Zone ID (and Account ID from Zone)
        zones_resp = cf_api(f"/zones?name={domain}", token)
        zones = zones_resp.get("result", [])
        if not zones:
            add_log(f"❌ Zone for domain '{domain}' not found in Cloudflare!")
            sync_state["status"] = f"Error: Zone {domain} missing"
            return
        zone_id = zones[0]["id"]

        if not account_id:
            zone_account = zones[0].get("account", {})
            account_id = zone_account.get("id")

        if not account_id:
            try:
                acc_resp = cf_api("/accounts", token)
                accounts = acc_resp.get("result", [])
                if accounts:
                    account_id = accounts[0]["id"]
            except Exception:
                pass

        if not account_id:
            add_log("❌ No Cloudflare accounts found for this token or zone!")
            sync_state["status"] = "Error: No Account"
            return

        # 2. Tunnel
        tunnels_resp = cf_api(f"/accounts/{account_id}/cfd_tunnel?name={tunnel_name}&is_deleted=false", token)
        tunnels = tunnels_resp.get("result", [])
        if tunnels:
            tunnel_id = tunnels[0]["id"]
        else:
            add_log(f"🔨 Creating Cloudflare Tunnel '{tunnel_name}'...")
            cr_resp = cf_api(
                f"/accounts/{account_id}/cfd_tunnel",
                token,
                method="POST",
                data={"name": tunnel_name, "config_src": "cloudflare"},
            )
            tunnel_id = cr_resp["result"]["id"]
            add_log(f"✅ Created Tunnel: {tunnel_id}")

        sync_state["tunnel_id"] = tunnel_id

        # 3. Retrieve Tunnel Token & write to shared volume for cloudflared
        token_resp = cf_api(f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token", token)
        tunnel_token = token_resp["result"]

        token_path = "/etc/cloudflared/token"
        old_token = ""
        if os.path.exists(token_path):
            try:
                with open(token_path, "r", encoding="utf-8") as f:
                    old_token = f.read().strip()
            except Exception:
                pass

        if old_token != tunnel_token:
            os.makedirs("/etc/cloudflared", exist_ok=True)
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(tunnel_token)
            add_log("🔑 Updated Cloudflare Tunnel Token in shared volume")

            try:
                cf_target = find_cloudflared_container_name()
                docker_api(f"/containers/{cf_target}/restart", method="POST")
                add_log(f"🔄 Triggered restart for cloudflared container ({cf_target})")
            except Exception as re:
                add_log(f"Notice restarting cloudflared: {re}")

        # 4. Discover Docker services
        try:
            services, all_containers = get_docker_containers()
        except Exception as e:
            add_log(f"Aborting sync: Docker container discovery error: {e}")
            sync_state["docker_connected"] = False
            sync_state["status"] = "Docker connection degraded"
            return

        if not sync_state.get("docker_connected", True):
            add_log("Aborting sync: Docker daemon connection is degraded or unreachable")
            sync_state["status"] = "Docker connection degraded"
            return
        sync_state["discovered_services"] = services
        sync_state["all_containers"] = all_containers

        discovered_names = [f"{s['hostname']} ({s['service']})" for s in services]
        add_log(f"🔍 Discovered Cloudflare-labeled services: {', '.join(discovered_names) if services else 'None'}")

        # 5. Build Cloudflare Tunnel Ingress Rules (Idempotent)
        ingress_rules = build_ingress_rules(services)

        if sync_state.get("_last_ingress") != ingress_rules:
            cf_api(
                f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
                token,
                method="PUT",
                data={"config": {"ingress": ingress_rules}},
            )
            sync_state["_last_ingress"] = ingress_rules
            add_log("✅ Updated Cloudflare Tunnel Ingress rules")

        # 6. DNS Records Sync (CNAME per subdomain, Idempotent)
        target_cname = f"{tunnel_id}.cfargotunnel.com"
        synced_dns = []
        for s in services:
            raw_host = s.get("hostname")
            host = normalize_hostname(raw_host)
            if not host:
                continue
            dns_resp = cf_api(f"/zones/{zone_id}/dns_records?type=CNAME&name={host}", token)
            records = dns_resp.get("result", [])
            dns_payload = {"type": "CNAME", "name": host, "content": target_cname, "proxied": True, "ttl": 1}
            if records:
                rec = records[0]
                rec_id = rec["id"]
                if rec.get("content") != target_cname or not rec.get("proxied"):
                    cf_api(f"/zones/{zone_id}/dns_records/{rec_id}", token, method="PUT", data=dns_payload)
                    add_log(f"🔄 Updated DNS record for {host}")
            else:
                cf_api(f"/zones/{zone_id}/dns_records", token, method="POST", data=dns_payload)
                add_log(f"➕ Created DNS record for {host}")
            synced_dns.append(
                {"hostname": host, "target": target_cname, "service": s.get("service", "unknown"), "proxied": True}
            )

        # 7. Cleanup obsolete DNS records with grace period / tombstoning
        current_hosts = {normalize_hostname(s["hostname"]) for s in services if normalize_hostname(s.get("hostname"))}
        tombstones = sync_state.setdefault("tombstones", {})
        now = time.time()

        # Clear tombstones for any active host that has recovered
        for host in current_hosts:
            if host in tombstones:
                del tombstones[host]
                add_log(f"Container recovered for {host}, cleared tombstone")

        immediate_cleanup = os.getenv("DNS_IMMEDIATE_CLEANUP", "false").lower() in ("true", "1", "yes")
        try:
            grace_period = float(os.getenv("DNS_CLEANUP_GRACE_PERIOD", 300.0))
        except ValueError:
            grace_period = 300.0

        all_dns = cf_api(f"/zones/{zone_id}/dns_records?type=CNAME&content={target_cname}", token)
        for rec in all_dns.get("result", []):
            rec_id = rec.get("id")
            raw_rec_name = rec.get("name", "")
            rec_name = normalize_hostname(raw_rec_name) or raw_rec_name.strip().rstrip(".").lower()
            if rec_name not in current_hosts:
                if immediate_cleanup or grace_period <= 0:
                    cf_api(f"/zones/{zone_id}/dns_records/{rec_id}", token, method="DELETE")
                    tombstones.pop(rec_name, None)
                    add_log(f"🗑️ Deleted obsolete DNS record for {rec_name}")
                else:
                    if rec_name not in tombstones:
                        tombstones[rec_name] = now
                        add_log(f"⏳ Tombstoned {rec_name} against flapping (grace period: {int(grace_period)}s)")
                    else:
                        elapsed = now - tombstones[rec_name]
                        if elapsed >= grace_period:
                            cf_api(f"/zones/{zone_id}/dns_records/{rec_id}", token, method="DELETE")
                            del tombstones[rec_name]
                            add_log(f"🗑️ Deleted obsolete DNS record for {rec_name} after grace period expired")
                        else:
                            remaining = int(grace_period - elapsed)
                            add_log(f"⏳ DNS record for {rec_name} preserved in tombstone ({remaining}s remaining)")
                            synced_dns.append(
                                {
                                    "hostname": rec_name,
                                    "target": target_cname,
                                    "service": "tombstoned",
                                    "proxied": True,
                                    "tombstone_remaining": remaining,
                                }
                            )

        sync_state["dns_records"] = synced_dns
        sync_state["status"] = "Active / Synced"
        sync_state["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
        add_log("🎉 Sync completed successfully!")

    except Exception as e:
        add_log(f"❌ Sync Error: {e}")
        sync_state["status"] = f"Error: {e}"
    finally:
        sync_lock.release()


event_listener_thread: Optional[threading.Thread] = None
event_stop_event: Optional[threading.Event] = None


async def fallback_sync_loop():
    while True:
        try:
            interval = int(
                os.getenv("SYNC_FALLBACK_INTERVAL", os.getenv("SYNC_INTERVAL", os.getenv("POLL_INTERVAL", 900)))
            )
            await asyncio.sleep(interval)
            add_log("Fallback periodic heartbeat sync triggered")
            await asyncio.to_thread(run_sync_logic)
        except asyncio.CancelledError:
            break
        except Exception as e:
            add_log(f"Unexpected loop exception: {e}")


sync_loop = fallback_sync_loop


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    global event_listener_thread, event_stop_event
    loop = asyncio.get_running_loop()
    debouncer.set_loop(loop)
    logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

    # Initial sync at startup
    asyncio.create_task(asyncio.to_thread(run_sync_logic))

    # Event stream listener
    event_stop_event = threading.Event()
    event_listener_thread = threading.Thread(
        target=listen_docker_events,
        args=(handle_docker_event, event_stop_event),
        daemon=True,
        name="docker-events-listener",
    )
    event_listener_thread.start()

    # Fallback sync loop
    fallback_task = asyncio.create_task(fallback_sync_loop())

    yield

    if event_stop_event:
        event_stop_event.set()
    fallback_task.cancel()


app = FastAPI(title="Cloudflare Tunnel & DNS Sync", lifespan=lifespan)


@app.get("/health")
@app.get("/healthz")
def health():
    docker_ok = sync_state.get("docker_connected", True)
    status_str = "healthy" if docker_ok else "degraded"
    return {"status": status_str, "docker_connected": docker_ok, "sync_status": sync_state.get("status")}


@app.get("/ready")
def ready(response: Response = None):
    docker_ok = sync_state.get("docker_connected", True)
    if not docker_ok and response:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if docker_ok else "not ready",
        "docker_connected": docker_ok,
        "sync_status": sync_state.get("status"),
    }


security = HTTPBasic(auto_error=False)


def check_dashboard_auth(credentials: Optional[HTTPBasicCredentials] = Depends(security)) -> bool:
    user = os.getenv("DASHBOARD_USERNAME", os.getenv("BASIC_AUTH_USERNAME", "")).strip()
    pwd = os.getenv("DASHBOARD_PASSWORD", os.getenv("BASIC_AUTH_PASSWORD", "")).strip()
    auth_enabled_env = os.getenv("DASHBOARD_AUTH_ENABLED", "").strip().lower()

    if auth_enabled_env in ("false", "0", "no"):
        return True

    auth_explicitly_enabled = auth_enabled_env in ("true", "1", "yes")

    if not auth_explicitly_enabled and not user and not pwd:
        return True

    # Fail-closed: Auth is enabled, but credentials are blank or unconfigured
    if not user or not pwd:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": 'Basic realm="Cloudflare Tunnel Sync Dashboard"'},
        )

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": 'Basic realm="Cloudflare Tunnel Sync Dashboard"'},
        )

    is_user_ok = secrets.compare_digest(credentials.username.encode("utf-8"), user.encode("utf-8"))
    is_pwd_ok = secrets.compare_digest(credentials.password.encode("utf-8"), pwd.encode("utf-8"))

    if not (is_user_ok and is_pwd_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": 'Basic realm="Cloudflare Tunnel Sync Dashboard"'},
        )

    return True


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard(authenticated: bool = Depends(check_dashboard_auth)):
    static_file = os.path.join(os.path.dirname(__file__), "static", "index.html")
    headers = {
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "object-src 'none'; "
            "base-uri 'self';"
        ),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
    if os.path.exists(static_file):
        with open(static_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), headers=headers)
    return HTMLResponse(
        content="<!DOCTYPE html><html><head><title>Cloudflare Tunnel Sync</title></head><body><h1>Cloudflare Tunnel Sync Dashboard</h1><p>Running in single-container mode. Access <a href='/api/status'>/api/status</a> for API data.</p></body></html>",
        headers=headers,
    )


def sanitize_sync_state(data: Any) -> Any:
    """Return a safely JSON-serializable public representation of sync state.

    Excludes internal private keys (starting with '_') from dictionaries and
    recursively converts non-serializable collections (such as set and frozenset)
    into sorted lists.
    """
    if isinstance(data, dict):
        items = list(data.items())
        return {k: sanitize_sync_state(v) for k, v in items if not k.startswith("_")}
    elif isinstance(data, (set, frozenset)):
        items = list(data)
        try:
            return sorted(sanitize_sync_state(x) for x in items)
        except TypeError:
            return [sanitize_sync_state(x) for x in items]
    elif isinstance(data, (list, tuple)):
        items = list(data)
        return [sanitize_sync_state(x) for x in items]
    return data


@app.get("/api/status")
def api_status(authenticated: bool = Depends(check_dashboard_auth)):
    return JSONResponse(sanitize_sync_state(sync_state))


@app.post("/api/sync")
async def api_sync(authenticated: bool = Depends(check_dashboard_auth)):
    await asyncio.to_thread(run_sync_logic)
    return JSONResponse({"message": "Sync triggered", "state": sanitize_sync_state(sync_state)})


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8090)
