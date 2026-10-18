# Configuration Reference

This document provides a comprehensive reference for all environment variables supported by `cf-tunnel-sync`.

---

## 📋 Environment Variables

### Core Cloudflare Credentials & Scope

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `CLOUDFLARE_API_TOKEN` | **Yes** | — | Cloudflare API Token with permissions: <br>• `Account → Cloudflare Tunnel → Edit`<br>• `Zone → DNS → Edit`<br>• `Zone → Zone → Read`. *(Alias: `CLOUDFLARE_TOKEN`)* |
| `CLOUDFLARE_ACCOUNT_ID` | **Yes** | — | 32-character hexadecimal Cloudflare Account ID (found in the Cloudflare dashboard sidebar under **Overview**). |
| `CLOUDFLARE_TUNNEL_NAME` | **Yes**\* | — | Name of the Cloudflare Tunnel. If the tunnel does not exist, `cf-tunnel-sync` automatically creates it upon first startup in standard sync mode. <br>\**Either `CLOUDFLARE_TUNNEL_NAME` or `CLOUDFLARE_TUNNEL_ID` is required.* |
| `CLOUDFLARE_TUNNEL_ID` | Optional | — | UUID of an existing Cloudflare Tunnel. If provided, `cf-tunnel-sync` binds directly to this tunnel without querying by name. |
| `DOMAIN_NAME` | Optional | — | Primary domain zone (e.g., `example.com`). If omitted, zone IDs are resolved dynamically based on container hostname labels. |
| `CLOUDFLARE_ZONE_ID` | Optional | — | Explicit Cloudflare DNS Zone ID. If omitted, resolved automatically via the `Zone:Read` permission on your API token. |

---

### Docker & Gateway Networking

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `CF_NETWORK_NAME` | Optional | auto-detected | Docker bridge network name connecting `cloudflared`, `cf-tunnel-sync`, and target service containers (e.g., `cf-tunnel-net`). |
| `CLOUDFLARED_CONTAINER_NAME` | Optional | `cloudflared` | Container name or alias of the `cloudflared` tunnel connector daemon. |
| `DOCKER_HOST` | Optional | `unix:///var/run/docker.sock` | Docker daemon connection socket or TCP endpoint. |

---

### Operational Modes & Diagnostics

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `PREFLIGHT_ONLY` | Optional | `false` | When set to `true` (or via `--preflight` CLI flag), runs strict, non-mutating validation of Docker socket access, Cloudflare credentials, and tunnel status, then exits (0 for pass, 1 for fail). **Never creates tunnels or mutates DNS/routes.** |
| `DRY_RUN` | Optional | `false` | When set to `true`, monitors Docker and computes tunnel ingress and DNS changes, logging planned operations without making API mutation calls. |
| `LOG_LEVEL` | Optional | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `SYNC_INTERVAL` | Optional | `30` | Periodic fallback synchronization polling interval in seconds. |
| `DEBOUNCE_DELAY` | Optional | `2.0` | Debounce stabilization window in seconds for rapid Docker container start/stop events before initiating synchronization. |

---

### Safety Guards & Circuit Breakers

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `MAX_DELETIONS_PER_SYNC` | Optional | `3` | Maximum number of route/DNS deletions allowed in a single synchronization cycle. Protects against accidental mass removal if Docker daemon restarts or containers temporarily stop. *(Alias: `MASS_DELETION_LIMIT`)* |
| `MAX_DELETION_RATIO` | Optional | — | Maximum percentage of routes that can be deleted in a single cycle (e.g., `0.50` for 50%). If exceeded, trips blast-radius protection. |
| `ALLOW_MASS_DELETIONS` | Optional | `false` | Circuit breaker override. Set to `true` only during deliberate mass teardowns or decommissioning of multiple services simultaneously. |
| `DNS_CLEANUP_GRACE_PERIOD` | Optional | `300` | Duration in seconds to tombstone stopped containers before removing their Cloudflare Tunnel Ingress rule and managed DNS record. |
| `DNS_IMMEDIATE_CLEANUP` | Optional | `false` | When `true`, immediately removes DNS records upon container shutdown, skipping the tombstone grace period. |
| `OWNERSHIP_POLICY` | Optional | `adopt_and_manage` | Ownership policy for Cloudflare DNS records: <br>• `adopt_and_manage` (default): tags matching unmanaged CNAMEs and manages them.<br>• `strict_tagged_only`: only mutates/deletes records explicitly tagged by this tunnel.<br>• `legacy_unrestricted`: backward compatibility mode for unmanaged legacy records. |

---

### Web Dashboard & Authentication

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `DASHBOARD_ENABLED` | Optional | `true` | Enables the built-in status and live log web dashboard (`ENABLE_DASHBOARD` is also accepted). |
| `DASHBOARD_PORT` | Optional | `5000` | Port on which the web dashboard listens inside the container. |
| `DASHBOARD_AUTH_ENABLED` | Optional | `false` | Enables HTTP Basic Authentication for accessing the web dashboard. |
| `DASHBOARD_USERNAME` | Optional | `admin` | Username required when `DASHBOARD_AUTH_ENABLED=true` (`BASIC_AUTH_USERNAME` is also accepted). |
| `DASHBOARD_PASSWORD` | Optional | — | Password required when `DASHBOARD_AUTH_ENABLED=true` (`BASIC_AUTH_PASSWORD` is also accepted). |

---

## ⚙️ Example Gateway Configuration (`.env`)

```env
# Cloudflare Credentials
CLOUDFLARE_API_TOKEN=cf_pat_your_secure_api_token
CLOUDFLARE_ACCOUNT_ID=0123456789abcdef0123456789abcdef
CLOUDFLARE_TUNNEL_NAME=production-gateway
DOMAIN_NAME=example.com

# Safety & Sync Tuning
MASS_DELETION_LIMIT=3
ALLOW_MASS_DELETIONS=false
LOG_LEVEL=INFO
```
