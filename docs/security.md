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

Both embedded and standalone dashboards enforce a strict Content Security Policy (`script-src 'self'`, `object-src 'none'`) with zero `'unsafe-inline'` script allowances and zero runtime CDN execution. UI scripts and styling are packaged self-contained into `/dashboard.js` and `/dashboard.css`.

## Public applications and Access metadata

A working tunnel makes a route reachable; it does not add application authorization. `cf.tunnel.access.policy` only annotates service status. Configure and verify the application's own authentication or a Cloudflare Access application/policy before treating an admin service as protected.

## Managed resource safety

DNS ownership comments, cleanup grace periods, and deletion limits reduce accidental changes. The default ownership policy can adopt matching untagged records for active services. Missing/null/empty ownership comments are not treated as ownership. Manual paths and duplicate ingress rules are preserved; the first root route for an active discovered hostname remains managed. Read [architecture and safety](architecture-and-safety.md#current-limitations) before using an existing tunnel or dry-run as a protection boundary.

For image identity and release artifacts, see [container releases](release-security.md).

## Non-breaking hardening additions (ISS-01..ISS-18)

- **ISS-01 socket proxy (opt-in):** example `examples/03-secure-socket-proxy` is the recommended opt-in for untrusted networks. Verify with `DOCKER_SOCKET_PROXY=1` acknowledgement in logs.
- **ISS-02 strict auth (opt-in):** `DASHBOARD_AUTH_REQUIRED=true` fails closed when credentials are missing, off by default. Put TLS/reverse proxy in front of a WAN-exposed dashboard; keep `/health` probes public. Do not expose `/api/status` or `/api/sync` without auth/TLS.
- **ISS-04 bind address:** default stays `0.0.0.0` for compatibility. On WAN use `DASHBOARD_BIND_ADDRESS=127.0.0.1` or the headless example without published ports.
- **ISS-05 token permissions (best-effort):** `FileTokenStore` attempts `0600` on the token file / `0700` on its directory with silent fallback; sync never fails on `chmod` errors. Docker secrets remain an opt-in alternative; set volume ACLs accordingly.
- **ISS-07 partial sync:** sync is convergent, not atomic. If ingress succeeds and DNS fails (or vice versa), status is `Degraded` with per-service stage status until the next cycle converges.
- **ISS-08 manual roots (opt-in):** `PRESERVE_MANUAL_ROOTS=true` (off by default) skips managed root replacement for unmanaged manual routes. Preflight lists existing root routes read-only.
- **ISS-09 ownership adoption:** every adoption under `adopt_and_manage` (default unchanged) emits a log/event (`DNS_ADOPTED`). For shared zones use `OWNERSHIP_POLICY=strict_tagged_only`.
- **ISS-11 tombstone persistence (opt-in):** `TOMBSTONE_PERSISTENCE_ENABLED=true` + `TOMBSTONE_PERSISTENCE_PATH` (default `/etc/cloudflared/tombstones.json`, contains only hostnames/timestamps, no secrets) persists tombstones; absent/corrupt files are ignored and never block sync. Default remains in-memory.
- **ISS-14 shutdown:** `Scheduler.close(timeout=45.0)` is idempotent; Python cannot forcibly stop blocked worker threads. Opt-in `SYNC_HEARTBEAT_ENABLED=true` logs heartbeat for long-running syncs.
