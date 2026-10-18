# Configuration Reference

This document provides a comprehensive reference for all configuration options supported by `cf-tunnel-sync`.

---

## ⚡ The Essential Three (Mandatory Settings)

For 95% of deployments, you only need to configure **three** environment variables. All other settings have production-ready defaults and automated discovery.

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `CLOUDFLARE_API_TOKEN` | **Yes** | — | Scoped Cloudflare API Token with permissions: <br>• `Account → Cloudflare Tunnel → Edit`<br>• `Zone → DNS → Edit`<br>• `Zone → Zone → Read`<br>*(Legacy alias: `CLOUDFLARE_TOKEN`)* |
| `CLOUDFLARE_TUNNEL_NAME` | **Yes**\* | — | Name of your Cloudflare Tunnel. If it does not exist, `cf-tunnel-sync` automatically provisions it upon first run.<br>\**Alternatively, specify an existing UUID via `CLOUDFLARE_TUNNEL_ID`.*<br>*(Legacy alias: `TUNNEL_NAME`)* |
| `DOMAIN_NAME` | **Yes** | — | Root domain zone managed in Cloudflare (e.g. `example.com`). Ingress hostnames without fully qualified domains are scoped to this zone automatically. |

> [!NOTE]
> **`CLOUDFLARE_ACCOUNT_ID` is strictly OPTIONAL.**  
> `cf-tunnel-sync` automatically resolves your Cloudflare Account ID via the domain zone or API token. You only need to set `CLOUDFLARE_ACCOUNT_ID` if your token has access to multiple accounts and you want to explicitly pin synchronization to a specific account.

---

## 🔍 Auto-Discovery & Precedence Rules

To eliminate unnecessary boilerplate while supporting advanced edge cases, `cf-tunnel-sync` resolves identifiers using the following precedence hierarchies:

### 1. Cloudflare Account ID Precedence
1. Explicit `CLOUDFLARE_ACCOUNT_ID` environment variable (highest priority).
2. Auto-discovery from the verified DNS Zone matching `DOMAIN_NAME`.
3. Auto-discovery from the list of accounts accessible by `CLOUDFLARE_API_TOKEN` (if exactly one account is accessible).

### 2. Cloudflare Tunnel Target Precedence
1. Explicit `CLOUDFLARE_TUNNEL_ID` UUID (bypasses name lookups).
2. `CLOUDFLARE_TUNNEL_NAME` (resolves existing tunnel by name or auto-provisions a new named tunnel).

### 3. Container Port Resolution Precedence
1. Explicit label `cf.tunnel.port` (or alias `cloudflared.port`).
2. Single exposed Docker port (if the container image exposes exactly one port via `EXPOSE`).
3. Fallback default: port `80` (with a diagnostic warning if multiple ports are exposed without an explicit label).

---

## 📋 Comprehensive Environment Variable Reference

### Core Cloudflare Credentials & Scope

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `CLOUDFLARE_API_TOKEN` | **Yes** | — | Cloudflare API Token. *(Alias: `CLOUDFLARE_TOKEN`)* |
| `CLOUDFLARE_TUNNEL_NAME` | **Yes**\* | — | Tunnel name. *(Alias: `TUNNEL_NAME`)* |
| `CLOUDFLARE_TUNNEL_ID` | Optional | — | UUID of an existing Cloudflare Tunnel. |
| `DOMAIN_NAME` | **Yes** | — | Root domain zone managed in Cloudflare (e.g., `example.com`). |
| `CLOUDFLARE_ACCOUNT_ID` | Optional | *auto-detected* | 32-character hexadecimal Account ID. Auto-detected if omitted. |
| `CLOUDFLARE_ZONE_ID` | Optional | *auto-detected* | Explicit Cloudflare DNS Zone ID. Auto-detected from `DOMAIN_NAME` if omitted. |
| `CLOUDFLARE_DNS_PROXIED`| Optional | `true` | Whether created CNAME DNS records are proxied through Cloudflare CDN (Orange cloud). *(Alias: `PROXIED`)* |
| `AUTO_CREATE_TUNNEL` | Optional | `true` | Automatically provisions the named tunnel in Cloudflare if it does not exist. |

---

### Docker & Gateway Networking

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `CF_NETWORK_NAME` | Optional | `cf-tunnel-net` | Docker bridge network connecting `cloudflared`, `cf-tunnel-sync`, and services. *(Alias: `CUSTOM_NETWORK`)* |
| `CLOUDFLARED_CONTAINER_NAME` | Optional | `cloudflared` | Container name of the `cloudflared` connector daemon. |
| `DOCKER_SOCKET` | Optional | `/var/run/docker.sock` | Path to Docker daemon socket. *(Alias: `DOCKER_SOCKET_PATH`)* |
| `DOCKER_HOST` | Optional | `unix:///var/run/docker.sock` | Docker daemon connection endpoint (e.g. `tcp://socket-proxy:2375`). |
| `REQUIRE_SHARED_NETWORK` | Optional | `false` | When `true`, excludes containers that do not share a network with `cloudflared`. *(Alias: `STRICT_NETWORK_CHECK`)* |

---

### Safety Guards & Circuit Breakers

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `MAX_DELETIONS_PER_SYNC` | Optional | `3` | Maximum route/DNS deletions allowed in a single synchronization cycle. Protects against accidental mass removal. *(Aliases: `MASS_DELETION_LIMIT`, `MAX_DELETIONS_THRESHOLD`, `MAX_DELETIONS_PER_RUN`)* |
| `MAX_DELETION_RATIO` | Optional | — | Maximum deletion fraction (e.g. `0.50` for 50%). Trips blast-radius circuit breaker if exceeded. |
| `ALLOW_MASS_DELETIONS` | Optional | `false` | Circuit breaker override. Set to `true` only during deliberate mass teardowns. |
| `DNS_CLEANUP_GRACE_PERIOD` | Optional | `300` | Duration in seconds to retain DNS records for stopped containers before deletion (tombstone grace period). |
| `DNS_IMMEDIATE_CLEANUP` | Optional | `false` | When `true`, immediately removes DNS records upon container shutdown, bypassing grace period. |
| `OWNERSHIP_POLICY` | Optional | `adopt_and_manage` | DNS ownership policy: <br>• `adopt_and_manage` (default): tags matching unmanaged CNAMEs and manages them.<br>• `strict_tagged_only`: only mutates/deletes records explicitly tagged by this tunnel.<br>• `legacy_unrestricted`: backward compatibility mode for unmanaged legacy records. |

---

### Synchronization & Debounce

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `SYNC_DEBOUNCE_SECONDS` | Optional | `2.5` | Debounce stabilization window in seconds to coalesce rapid container churn. *(Aliases: `DEBOUNCE_WAIT_SECONDS`, `DEBOUNCE_SECONDS`, `SYNC_DEBOUNCE_DELAY`)* |
| `SYNC_DEBOUNCE_MAX_DELAY`| Optional | `10.0` | Maximum debounce delay before forcing an evaluation run. |
| `SYNC_FALLBACK_INTERVAL`| Optional | `900` | Periodic fallback synchronization heartbeat in seconds. *(Aliases: `SYNC_INTERVAL`, `POLL_INTERVAL`, `FALLBACK_INTERVAL`)* |
| `INITIAL_DELAY` | Optional | `1.0` | Delay in seconds before running the initial startup reconcile. |

---

### Observability, Web Dashboard & Prometheus

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `DASHBOARD_ENABLED` | Optional | `true` | Enables the embedded status and log web dashboard. |
| `DASHBOARD_PORT` | Optional | `8090` | Internal HTTP listening port for API, dashboard, and metrics. *(Alias: `PORT`)* |
| `DASHBOARD_BIND_ADDRESS`| Optional | `0.0.0.0` | IP bind address for the HTTP server. |
| `DASHBOARD_AUTH_ENABLED`| Optional | `false` | Enables HTTP Basic Authentication for web dashboard and status endpoints. |
| `DASHBOARD_USERNAME` | Optional | `admin` | Username for dashboard basic auth. *(Alias: `BASIC_AUTH_USERNAME`)* |
| `DASHBOARD_PASSWORD` | Optional | — | Password for dashboard basic auth. *(Alias: `BASIC_AUTH_PASSWORD`)* |
| `METRICS_AUTH_ENABLED` | Optional | `false` | Enforces Basic Auth on `/metrics`. Defaults to `false` for unauthenticated Prometheus scrapers. |
| `LOG_LEVEL` | Optional | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `LOG_FORMAT` | Optional | `text` | Log format: `text` (human-readable) or `json` (structured machine parsing). |
| `NOTIFICATION_WEBHOOK_URL`| Optional | — | Webhook URL for operational alert notifications (Discord, Slack, or generic HTTP POST). |
| `NOTIFICATION_WEBHOOK_TYPE`| Optional | `auto` | Webhook payload format: `auto`, `discord`, `slack`, or `generic`. |
| `NOTIFICATION_COOLDOWN_SECONDS`| Optional | `300` | Cooldown period between duplicate alert notifications. |

---

### Operational Modes & Diagnostics

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `PREFLIGHT_ONLY` | Optional | `false` | When `true` (or via `--preflight` CLI flag), performs non-mutating validation of Docker, Cloudflare API, DNS zones, and ports, then exits (0 for success, 1 for failure). |
| `DRY_RUN` | Optional | `false` | Computes ChangePlan and logs planned ingress and DNS changes without executing mutations. |
