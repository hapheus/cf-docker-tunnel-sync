# Compatibility Baseline & Supported Behavior Matrix (v1.13.0 Baseline)

This document establishes the official supported-behavior baseline, configuration schema, and upgrade invariants for `cf-docker-tunnel-sync`, covering the transition from v1.13.0 forward (Milestone 0: Issues #83-#90).

---

## 1. Supported Deployment Topologies

The sync engine guarantees zero configuration disruption and deterministic behavior across the following deployment topologies:

1. **Single-Compose Topology (`examples/01-single-compose`):**
   - Cloudflare Tunnel connector, `cf-docker-tunnel-sync`, and proxied service containers coexist in a single `docker-compose.yml` sharing an internal bridge network (`cf-tunnel-net`).
   - Origins resolve directly via Docker internal DNS names and published/target container ports.

2. **Multi-Compose Topology (`examples/02-multi-compose`):**
   - Cloudflare Tunnel connector runs in an infrastructure compose project.
   - Application services run in independent compose projects, attached to an external shared Docker network (`cf-tunnel-net`).
   - Discovery discovers origins across arbitrary compose projects and associates them with the designated tunnel.

3. **Multi-Account & Multi-Tunnel Scoping (`examples/03-multi-account`):**
   - Containers use `cf.tunnel.name` to bind to specific tunnels.
   - Sync engine processes only containers matching its configured `CLOUDFLARE_TUNNEL_NAME`, ignoring foreign or un-scoped containers without throwing warnings.

4. **Custom Bridge Networks & Host Networking:**
   - Supports custom bridge networks defined by `CF_NETWORK_NAME`.
   - Host networking fallback uses container IP or `HOST_IP` when Docker internal bridge DNS is bypassed.

---

## 2. Configuration & Environment Variables

All 28 supported configuration environment variables must remain strictly additive. No variable may be removed or have its semantic type changed without a major version milestone.

| Environment Variable | Type | Default | Description |
|---|---|---|---|
| `CLOUDFLARE_API_TOKEN` | String (Secret) | *Required* | Scoped Cloudflare API token (`Zone:DNS:Edit`, `Account:Cloudflare Tunnel:Edit`). |
| `CLOUDFLARE_ACCOUNT_ID` | String | *Required* | 32-character hexadecimal Cloudflare account identifier. |
| `CLOUDFLARE_TUNNEL_NAME` | String | `"cf-docker-tunnel-sync"` | Name of the Cloudflare Tunnel managed by this instance. |
| `CLOUDFLARE_TUNNEL_ID` | String (UUID) | Auto-discovered | 36-character UUID of the Cloudflare Tunnel. |
| `CF_NETWORK_NAME` | String | `"cf-tunnel-net"` | Docker network name inspected for container connectivity. |
| `CLOUDFLARED_PROTOCOL` | String | `"auto"` | Tunnel transport protocol (`auto`, `quic`, `http2`). |
| `DRY_RUN` | Boolean | `false` | When `true`, preview reconciliation plans without calling Cloudflare mutating APIs. |
| `ALLOW_MASS_DELETIONS` | Boolean | `false` | Safety bypass to permit deletions exceeding threshold. |
| `MAX_DELETIONS_THRESHOLD` | Integer | `3` | Maximum allowed destructive deletions in a single sync loop before triggering blast-radius abort. |
| `INITIAL_DELAY` | Integer | `5` | Startup wait time (seconds) before initial reconciliation. |
| `DEBOUNCE_SECONDS` | Float | `2.0` | Event debouncing window for Docker container lifecycle events. |
| `FALLBACK_INTERVAL` | Integer | `300` | Periodic fallback reconciliation interval (seconds). |
| `LOG_LEVEL` | String | `"INFO"` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `LOG_FORMAT` | String | `"text"` | Log structure: `"text"` (human-readable) or `"json"` (single-line JSON). |
| `PROMETHEUS_METRICS_ENABLED` | Boolean | `true` | Exposes Prometheus exposition endpoint at `/metrics`. |
| `PROMETHEUS_PORT` | Integer | `8000` | Port for standalone Prometheus metrics server if enabled. |
| `NOTIFICATION_WEBHOOK_URL` | String | `""` | Webhook URL for alerting on sync failures and blast-radius aborts. |
| `NOTIFICATION_COOLDOWN_SECONDS` | Integer | `300` | Minimum interval between webhook alert dispatches. |
| `STRICT_HEALTH_STATUS` | Boolean | `false` | When `true`, `/health` returns 503 if Docker daemon is unreachable. |
| `DASHBOARD_ENABLED` | Boolean | `true` | Enables embedded status dashboard. |
| `DASHBOARD_PORT` | Integer | `8080` | Port for the embedded status dashboard. |
| `DASHBOARD_BIND_ADDRESS` | String | `"0.0.0.0"` | Listen address for embedded dashboard. |
| `DASHBOARD_AUTH_ENABLED` | Boolean | `false` | Enables HTTP Basic Auth on dashboard and API routes. |
| `BASIC_AUTH_USERNAME` | String | `""` | Username for dashboard Basic Auth. |
| `BASIC_AUTH_PASSWORD` | String | `""` | Password for dashboard Basic Auth. |
| `CLOUDFLARE_MAX_RETRIES` | Integer | `3` | Maximum retry attempts for Cloudflare API calls. |
| `CLOUDFLARE_RETRY_BASE_DELAY` | Float | `1.0` | Base exponential backoff delay (seconds) for rate limits/errors. |
| `HOST_IP` | String | `""` | Optional host IP override for host-mode networking. |

---

## 3. Historical Label Aliases & Precedence

All historical and shorthand labels are guaranteed 100% backward compatibility:

| Historical / Alias Label | Canonical Equivalent |
|---|---|
| `cloudflared.hostname` | `cf.tunnel.hostname` |
| `cloudflared.domain` | `cf.tunnel.domain` |
| `cftunnel.domain` | `cf.tunnel.domain` |
| `cftunnel.hostname` | `cf.tunnel.hostname` |
| `cloudflared.service` | `cf.tunnel.service` |
| `cftunnel.service` | `cf.tunnel.service` |
| `cloudflared.port` | `cf.tunnel.port` |
| `cftunnel.port` | `cf.tunnel.port` |
| `cloudflared.proto` | `cf.tunnel.proto` |
| `cftunnel.proto` | `cf.tunnel.proto` |
| `cloudflared.protocol` | `cf.tunnel.protocol` |
| `cftunnel.protocol` | `cf.tunnel.protocol` |
| `cloudflared.scheme` | `cf.tunnel.scheme` |
| `cftunnel.scheme` | `cf.tunnel.scheme` |
| `cloudflared.name` | `cf.tunnel.name` |
| `cftunnel.name` | `cf.tunnel.name` |
| `cloudflared.tunnel` | `cf.tunnel.name` |
| `cftunnel.tunnel` | `cf.tunnel.name` |
| `cloudflared.enable` | `cf.tunnel.enable` |
| `cftunnel.enable` | `cf.tunnel.enable` |
| `cloudflared.path` | `cf.tunnel.path` |
| `cftunnel.path` | `cf.tunnel.path` |
| `cloudflared.notlsverify` | `cf.tunnel.origin_request.no_tls_verify` |
| `cftunnel.notlsverify` | `cf.tunnel.origin_request.no_tls_verify` |
| `cloudflared.notls_verify` | `cf.tunnel.origin_request.no_tls_verify` |
| `cftunnel.notls_verify` | `cf.tunnel.origin_request.no_tls_verify` |
| `cloudflared.origin_server_name` | `cf.tunnel.originRequest.originServerName` |
| `cftunnel.origin_server_name` | `cf.tunnel.originRequest.originServerName` |
| `cloudflared.access.policy` | `cf.tunnel.access.policy` |
| `cftunnel.access.policy` | `cf.tunnel.access.policy` |

**Precedence Order:**
When multiple conflicting labels are present on the same container:
1. `cf.tunnel.*` (Canonical modern label — takes highest precedence)
2. `cloudflared.*` (Standard legacy prefix)
3. `cftunnel.*` (Shorthand legacy prefix)

---

## 4. Cloudflare Ingress & DNS Invariants

1. **Zero Unintended Mutations:** Upgrading image or sync engine without changing container state results in `ChangePlan.has_mutations == false`.
2. **Resource Ownership Isolation:** Only DNS records bearing the designated tag (`cf-tunnel-sync:<tunnel_name>`) and pointing to `<tunnel_id>.cfargotunnel.com` are managed. Foreign and unmanaged records are strictly preserved (`OwnershipStatus.FOREIGN` / `OwnershipStatus.UNRELATED`).
3. **Graceful Tombstoning & Stop/Restart:**
   - When a managed container stops, its ingress route is removed, and its DNS record is tombstoned.
   - If the container restarts, the tombstone is cleared, and the route and DNS are seamlessly restored without DNS record re-creation or downtime.
4. **Blast-Radius Guard:** Destructive deletions exceeding `MAX_DELETIONS_THRESHOLD` abort reconciliation and trigger webhook notifications without mutating Cloudflare resources.

---

## 5. API Contracts & Observability

- **`GET /health` & `GET /healthz`:**
  - Status: 200 (healthy) or 503 (degraded)
  - Fields: `status`, `version`, `uptime_seconds`, `docker_connected`, `last_sync`
- **`GET /api/status`:**
  - Status: 200 OK (Basic Auth protected if `DASHBOARD_AUTH_ENABLED=true`)
  - Fields: `status`, `docker_connected`, `active_tunnel`, `account_id`, `tunnel_id`, `tunnel_name`, `discovered_services`, `all_containers`, `logs`, `metrics`, `uptime_seconds`
- **`GET /api/change-plan` & `GET /api/v1/sync/preview`:**
  - Fields: `actions` (list of planned ingress and DNS changes), `summary` (change counts and safety abort status)
- **`GET /metrics`:**
  - Prometheus exposition format text (`text/plain; version=0.0.4; charset=utf-8`)
  - Metrics: `cf_tunnel_sync_operations_total`, `cf_tunnel_sync_duration_seconds`, `cf_tunnel_managed_routes_total`, `cf_tunnel_managed_dns_records_total`, `cf_tunnel_healthy_containers_total`.
