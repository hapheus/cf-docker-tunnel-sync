# Security

The synchronizer handles a Cloudflare API token, a connector token, and Docker host metadata. Keep the controller and its status API on a trusted network. Application authentication must be configured separately.

## Docker socket access

Mounting `/var/run/docker.sock:ro` does not make the Docker API read-only. The mount restricts filesystem access to the socket node; HTTP requests over that socket can still control Docker. Treat an unfiltered Docker socket as privileged host access.

Normal discovery reads `/containers/json` and `/events`. When the connector token changes, the synchronizer also attempts `POST /containers/<connector>/restart`.

A socket proxy can restrict API access:

```text
synchronizer -> private proxy network -> socket proxy -> Docker socket
```

The [socket-proxy example](../examples/03-secure-socket-proxy/README.md) permits container/event reads and blocks POST requests. This reduces authority but prevents automatic connector restart. After token initialization or replacement, check connector logs and restart the connector yourself if needed. Keep the proxy's TCP port private; the current client uses plain HTTP, without Docker TLS configuration.

## Cloudflare credentials

Use a scoped API token limited to the intended account and zone. The service needs tunnel editing, DNS editing, and zone lookup permissions; see [token setup](cloudflare-permissions.md). Avoid the Global API Key.

The connector token is written to `/etc/cloudflared/token` on a shared volume. Limit access to that volume and to `.env` files. Stopping the service does not revoke either credential.

The service masks recognized secrets in logs, API output, and webhook payloads. Redaction is a safeguard, not a reason to include raw credentials in arbitrary messages or support reports. Check outputs before sharing them.

## Dashboard and metrics

The backend listens on `0.0.0.0:8090`; the root Compose file publishes host port 8080. With that Compose file, set `DASHBOARD_BIND_ADDRESS=127.0.0.1` to restrict the published port to the local host, or use the [headless example](../examples/02-multi-stack-external-net/core-tunnel-stack/docker-compose.headless.yml) without published ports.

Configure a nonempty dashboard username and password. The root Compose file enables authentication by default and rejects protected requests if credentials are missing. Bare-image behavior and metric authentication differ; see [configuration](configuration.md).

Basic authentication does not encrypt traffic. Use a trusted local connection or TLS in front of an exposed dashboard. `/health`, `/healthz`, and `/ready` are public probes; `/metrics` is public unless `METRICS_AUTH_ENABLED=true`. Disabling the dashboard UI does not disable the API.

The optional companion dashboard has its own authentication and proxies requests to the backend. Configure both layers deliberately rather than assuming frontend authentication protects a separately published backend.

## Public applications and Access metadata

A working tunnel makes a route reachable; it does not add application authorization. `cf.tunnel.access.policy` only annotates service status. Configure and verify the application's own authentication or a Cloudflare Access application/policy before treating an admin service as protected.

## Managed resource safety

DNS ownership comments, cleanup grace periods, and deletion limits reduce accidental changes. The default ownership policy can adopt matching untagged records for active services. Missing/null/empty ownership comments are not treated as ownership. Manual paths and duplicate ingress rules are preserved; the first root route for an active discovered hostname remains managed. Read [architecture and safety](architecture-and-safety.md#current-limitations) before using an existing tunnel or dry-run as a protection boundary.

For image identity and release artifacts, see [container releases](release-security.md).
