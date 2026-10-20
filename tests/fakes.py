"""Stateful, isolated Docker/Cloudflare fixtures for service tests."""

from copy import deepcopy

from tunnel_sync.bootstrap import create_services
from tunnel_sync.configuration.settings import Settings
from tunnel_sync.domain.models import RemoteState


class MemoryTokenStore:
    def __init__(self, token="old-token"):
        self.token = token
        self.reads = 0
        self.writes = []

    def read(self):
        self.reads += 1
        return self.token

    def write(self, token):
        self.writes.append(token)
        self.token = token


class FakeDocker:
    def __init__(self, containers=(), unavailable=False):
        self.containers = list(containers)
        self.unavailable = unavailable
        self.restarts = []
        self.closed = False

    def request(self, path, method="GET", **kwargs):
        if self.unavailable:
            raise ConnectionError("Docker unavailable")
        if method == "POST":
            assert path.endswith("/restart")
            self.restarts.append(path)
            return {}
        if path == "/version":
            return {"Version": "test"}
        assert path == "/containers/json?all=true"
        return deepcopy(self.containers)

    def listen_events(self, callback, stop_event):
        stop_event.wait()

    def close_events(self):
        self.closed = True


class FakeCloudflare:
    def __init__(self, tunnel_exists=True):
        self.tunnel_exists = tunnel_exists
        self.config = {"ingress": [{"service": "http_status:404"}], "warp-routing": {"enabled": True}}
        self.dns = []
        self.calls = []
        self.fail_ingress = False
        self.fail_dns = False

    def request(self, endpoint, token, method="GET", data=None):
        self.calls.append((method, endpoint, deepcopy(data)))
        if endpoint.startswith("/zones?"):
            return {"result": [{"id": "zone", "account": {"id": "account"}}]}
        if "/cfd_tunnel?" in endpoint:
            return {"result": [{"id": "real-tunnel"}] if self.tunnel_exists else []}
        if endpoint == "/accounts/account/cfd_tunnel":
            assert method == "POST"
            self.tunnel_exists = True
            return {"result": {"id": "real-tunnel"}}
        if endpoint.endswith("/token"):
            return {"result": "new-token"}
        if endpoint.endswith("/configurations"):
            assert "/real-tunnel/" in endpoint
            if method == "PUT":
                if self.fail_ingress:
                    raise RuntimeError("ingress unavailable")
                self.config = deepcopy(data["config"])
            return {"result": {"config": deepcopy(self.config)}}
        if "/dns_records" in endpoint:
            if method != "GET" and self.fail_dns:
                raise RuntimeError("DNS unavailable")
            if method == "POST":
                self.dns.append({"id": f"dns-{len(self.dns)}", **data})
            elif method == "PUT":
                for record in self.dns:
                    if endpoint.endswith("/" + record["id"]):
                        record.update(data)
            elif method == "DELETE":
                self.dns = [record for record in self.dns if not endpoint.endswith("/" + record["id"])]
            return {"result": deepcopy(self.dns)}
        raise AssertionError(f"Unexpected request: {method} {endpoint}")

    @property
    def mutations(self):
        return [call for call in self.calls if call[0] != "GET"]


def container():
    return {
        "Id": "web-id",
        "Names": ["/web"],
        "State": "running",
        "Status": "Up",
        "Image": "nginx",
        "Labels": {"cf.tunnel.hostname": "web.example.com", "cf.tunnel.port": "80"},
        "NetworkSettings": {"Networks": {"cf-tunnel-net": {}}},
    }


def composition(*, cloudflare=None, docker=None, **environment):
    cloudflare = cloudflare if cloudflare is not None else FakeCloudflare()
    docker = docker if docker is not None else FakeDocker([container()])
    store = MemoryTokenStore()
    settings = Settings(
        {
            "DOMAIN_NAME": "example.com",
            "CLOUDFLARE_API_TOKEN": "dummy-token",
            "CLOUDFLARED_CONTAINER_NAME": "cloudflared",
            **environment,
        }
    )
    services = create_services(settings, cloudflare_request=cloudflare.request, docker=docker, token_store=store)
    return services, cloudflare, docker, store


def remote(rules):
    return RemoteState(
        tunnel_id="real-tunnel",
        tunnel_name="test",
        zone_id="zone",
        tunnel_target="real-tunnel.cfargotunnel.com",
        existing_ingress_rules=rules,
    )
