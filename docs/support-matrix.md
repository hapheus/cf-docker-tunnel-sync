# Support Matrix, Compatibility & Version Lifecycle

This document defines the supported host platforms, container engines, Cloudflare account tiers, known constraints, and version lifecycle policy for `cf-docker-tunnel-sync`.

---

## 🖥️ Platform & Architecture Support

| Component | Supported | Notes |
| :--- | :--- | :--- |
| **Linux amd64 (`x86_64`)** | ✅ Fully Supported | Standard Intel/AMD 64-bit servers, VPS, cloud instances |
| **Linux arm64 (`aarch64`)** | ✅ Fully Supported | ARMv8+, Raspberry Pi 4 / 5, Apple Silicon VMs, Oracle Cloud Ampere |
| **Linux armv7 (`32-bit`)** | ⚠️ Community Best Effort | Older 32-bit ARM boards (e.g., Raspberry Pi 2/3 in 32-bit mode) |
| **macOS (Docker Desktop / OrbStack)** | ✅ Supported | Local development & testing |
| **Windows (WSL2 Docker Desktop)** | ✅ Supported | Linux containers via WSL2 backend |
| **Native Windows Containers** | ❌ Not Supported | Only Linux-based container runtimes are supported |

---

## 🐳 Container Runtime & Compose Matrix

| Requirement | Minimum Version | Recommended Version |
| :--- | :--- | :--- |
| **Docker Engine** | `20.10.0+` | `26.x` / `27.x` / `28.x` |
| **Docker Compose** | `v2.0.0+` (`docker compose`) | `v2.24+` |
| **Docker API Version** | `1.41+` | `1.44+` |
| **Docker Socket Proxy** | `Tecativa` / `Wollomatic` | Read-only TCP proxy (`tcp://socket-proxy:2375`) |
| **Docker Swarm / Kubernetes** | ⚠️ Standalone Engine Only | Designed specifically for Docker Engine / Compose |

---

## ☁️ Cloudflare Prerequisites

| Feature | Supported Tiers | Requirements |
| :--- | :--- | :--- |
| **Cloudflare Account Tier** | Free, Pro, Business, Enterprise | Any Cloudflare account with at least one active domain zone |
| **Cloudflare Zero Trust** | Free Plan (up to 50 users) and paid | Zero Trust enabled on the account |
| **Cloudflare Tunnel Type** | Remotely-managed named tunnels | Automatically provisions or manages named Cloudflare Tunnels |
| **API Token Scope** | Scoped Token (Recommended) | `Account → Cloudflare Tunnel:Edit`, `Zone → DNS:Edit`, `Zone → Zone:Read` |
| **Account ID** | Optional | Auto-detected from zone or token; only required to pin a specific account |

---

## ⚠️ Known Operational Boundaries

1. **Host Port Forwarding**: `cf-tunnel-sync` communicates over private Docker bridge networks. Do not expose host ports (`ports: "80:80"`) unless local LAN access is specifically required.
2. **Blast Radius Protection**: By default, `MAX_DELETIONS_PER_SYNC=3` prevents accidental bulk deletion of Cloudflare DNS records if Docker daemon restarts. Set `ALLOW_MASS_DELETIONS=true` if intentionally tearing down >3 services at once.
3. **Cloudflare API Rate Limiting**: The reconciler includes exponential backoff with jitter and respects HTTP 429 rate limit responses.
4. **Tombstone Retention**: Stopped containers retain their DNS records for 300 seconds (`DNS_CLEANUP_GRACE_PERIOD=300`) to prevent DNS churn during quick container restarts or redeploys.

---

## 🔄 Version Lifecycle & Compatibility Guarantee

* **Zero Breaking Changes Policy**: We guarantee that updating to any newer `v1.x.y` version will **never** break an existing setup, invalidate an existing label, change default behavior, or require manual configuration migration.
* **Deprecation Policy**: Legacy environment variables (`CLOUDFLARE_TOKEN`, `BASIC_AUTH_USERNAME`, `SYNC_INTERVAL`) and historical labels (`cloudflared.*`) remain permanently aliased and fully supported throughout the `v1.x` lifecycle.
* **Release Channels**:
  - `hapheus/cf-tunnel-sync:1.19.0` (Immutable SemVer, Recommended for Production)
  - `hapheus/cf-tunnel-sync:1` (Floating major)
  - `hapheus/cf-tunnel-sync:latest` (Floating latest stable release)
