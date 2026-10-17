# 🚀 Cloudflare Tunnel & Docker Sync

[![Docker Image Version](https://img.shields.io/docker/v/hapheus/cf-tunnel-sync?sort=semver&logo=docker&logoColor=white)](https://hub.docker.com/r/hapheus/cf-tunnel-sync)
[![Docker Pulls](https://img.shields.io/docker/pulls/hapheus/cf-tunnel-sync?logo=docker&logoColor=white)](https://hub.docker.com/r/hapheus/cf-tunnel-sync)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

`hapheus/cf-tunnel-sync` automatically discovers Docker containers across your host and synchronizes Cloudflare Zero Trust Tunnel ingress rules and proxied DNS (CNAME) records in real time.

---

## ✨ Features

- 🔄 **Real-Time Docker Discovery:** Automatically provisions ingress rules and DNS records when containers start or stop.
- 🎯 **Fine-Grained Label Control:** Configure custom hostnames, service protocols (`http://`, `https://`, `tcp://`), subpaths, and ports.
- 🔒 **Zero Trust & Access Integration:** Attach Cloudflare Access service tokens and custom origin request configurations.
- 🏢 **Multi-Account & Multi-Tunnel:** Route different compose stacks to distinct Cloudflare accounts and tunnels seamlessly.
- 🛡️ **Blast-Radius Protection & Deletion Guard:** Automatically prevents bulk route teardown on engine restart with configurable limits (`MAX_DELETIONS_PER_SYNC=3`).
- 🔍 **Non-Mutating Preflight Validation:** Validate Docker, tokens, and tunnels without mutations via `--preflight` or `PREFLIGHT_ONLY=true`.
- 🔮 **Predictive Dry-Run & ChangePlan API:** Audit exact route mutations via `--dry-run` and `GET /api/change-plan`.
- 🔬 **6-Stage Truthful Diagnostics:** Granular health checks ensuring zero false-positive sync reporting.
- 📊 **Status Dashboard & Web UI:** Built-in dashboard with real-time stage status indicators.

---

## 🚀 Quick Start with Docker Compose

Deploy the core gateway stack alongside `cloudflared`:

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    restart: unless-stopped
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    networks:
      - tunnel_net

  cf-tunnel-sync:
    image: hapheus/cf-tunnel-sync:latest
    container_name: cf-tunnel-sync
    restart: unless-stopped
    environment:
      - CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}
      - CLOUDFLARE_ACCOUNT_ID=${CLOUDFLARE_ACCOUNT_ID}
      - CLOUDFLARE_TUNNEL_NAME=${CLOUDFLARE_TUNNEL_NAME}
      - DOMAIN_NAME=${DOMAIN_NAME}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - tunnel_net

networks:
  tunnel_net:
    name: tunnel_net
```

---

## 🏷️ Container Labels Reference

Enable any container for automatic synchronization by applying Docker labels:

| Label | Description | Example |
|---|---|---|
| `cf.tunnel.enable` | Enable tunnel synchronization (`true` or `false`). | `true` |
| `cf.tunnel.hostname` | Fully qualified domain name for public ingress. | `app.example.com` |
| `cf.tunnel.port` | Target port inside the container (auto-detected if single port exposed). | `8080` |
| `cf.tunnel.service` | Target service URL / protocol override. | `http://app:8080` or `https://app:8443` |
| `cf.tunnel.path` | Optional path prefix for path-based routing. | `/api` |
| `cf.tunnel.originRequest.noTLSVerify` | Disable TLS certificate verification for upstream. | `true` |
| `cf.tunnel.originRequest.httpHostHeader` | Custom HTTP Host header sent to upstream service. | `backend.local` |
| `cf.tunnel.originRequest.originServerName` | SNI hostname for upstream TLS handshake. | `backend.local` |
| `cf.tunnel.access.aud` | Cloudflare Access Application AUD tag for validation. | `<AUD_KEY>` |

---

## ⚙️ Core Configuration Reference

| Variable | Required | Default | Description |
|---|:---:|---|---|
| `CLOUDFLARE_API_TOKEN` | Yes | *none* | Cloudflare API Token with `Zone:DNS:Edit` and `Account:Cloudflare Tunnel:Edit` permissions. |
| `CLOUDFLARE_ACCOUNT_ID` | Yes | *none* | Cloudflare Account ID. |
| `CLOUDFLARE_TUNNEL_NAME` | Yes* | *none* | Name of the Cloudflare Zero Trust Tunnel (*or specify `CLOUDFLARE_TUNNEL_ID`). |
| `CLOUDFLARE_TUNNEL_ID` | No | *auto-detected* | Explicit Cloudflare Tunnel UUID. |
| `CLOUDFLARE_ZONE_ID` | No | *auto-detected* | Explicit Zone ID for the root domain. |
| `DOMAIN_NAME` | Yes | *none* | Root domain managed in Cloudflare (e.g. `example.com`). |
| `POLL_INTERVAL` | No | `30` | Fallback polling interval in seconds for Docker state reconciliation. |
| `SYNC_ON_STARTUP` | No | `true` | Reconcile all existing running containers immediately on startup. |
| `LOG_LEVEL` | No | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `DRY_RUN` | No | `false` | When `true`, logs planned Cloudflare API actions without making changes. |
| `DOCKER_HOST` | No | `unix:///var/run/docker.sock` | Docker daemon socket URI. |
| `STATUS_PAGE_ENABLED` | No | `true` | Enable internal API & status endpoint on port `8090`. |
| `STATUS_PAGE_PORT` | No | `8090` | Internal status API listening port. |
| `METRICS_ENABLED` | No | `true` | Expose Prometheus metrics at `/metrics`. |

---

## 📊 Web Dashboard

To access the visual web UI:
- **Embedded:** If `STATUS_PAGE_ENABLED=true`, the internal status endpoint is active on port `8090`.
- **Companion Nginx Dashboard:** Deploy [`hapheus/cf-tunnel-dashboard`](https://hub.docker.com/r/hapheus/cf-tunnel-dashboard) on the same network for a secured UI with HTTP Basic Authentication and modern styling.

---

## 🔗 Links & Resources

- **Dashboard Image:** [`hapheus/cf-tunnel-dashboard`](https://hub.docker.com/r/hapheus/cf-tunnel-dashboard)
- **Source Code & Documentation:** [github.com/hapheus/cf-docker-tunnel-sync](https://github.com/hapheus/cf-docker-tunnel-sync)
- **Issue Tracker:** [github.com/hapheus/cf-docker-tunnel-sync/issues](https://github.com/hapheus/cf-docker-tunnel-sync/issues)
