# 📁 Architecture Examples & Topologies

This directory contains battle-tested, copy-paste-ready Docker Compose configurations for every common deployment topology.

---

## Example Catalog

| Directory | Topology / Use Case | Recommended For |
| :--- | :--- | :--- |
| **[`01-quickstart-single-stack`](01-quickstart-single-stack/README.md)** | **60-Second Quickstart**: Sync daemon + `cloudflared` + demo app in one file. | First-time evaluations & simple servers |
| **[`02-multi-stack-external-net`](02-multi-stack-external-net/README.md)** | **Decoupled Gateway & Multi-App Stacks**: Connected via shared external bridge network (`cf-tunnel-net`). | **Recommended Production & Homelab** |
| **[`03-secure-socket-proxy`](03-secure-socket-proxy/README.md)** | **Hardened Docker Socket Security**: Zero direct socket mount using `tecnativa/docker-socket-proxy` (TCP read-only). | Security-sensitive & enterprise environments |
| **[`04-advanced-labels-tls-multiport`](04-advanced-labels-tls-multiport/README.md)** | **Complex Backends**: Self-signed internal HTTPS (`noTLSVerify`), custom `Host` header rewrite, multi-port disambiguation. | Proxmox, Nextcloud, TrueNAS, Portainer, MinIO |
| **[`05-multi-account`](05-multi-account/README.md)** | **Multi-Account & Multi-Tunnel Scoping**: Running independent sync instances per business/personal account. | Multi-tenant & multi-account setups |

---

## Core Invariant Across All Examples

Every example adheres strictly to the canonical zero-configuration token contract:
- `cloudflared` runs:
  ```yaml
  command: tunnel --no-autoupdate run --token-file /etc/cloudflared/token
  volumes:
    - cf_token_data:/etc/cloudflared
  depends_on:
    cf-tunnel-sync:
      condition: service_healthy
  ```
- `cf-tunnel-sync` communicates with Cloudflare API, retrieves or creates the tunnel token, writes it to `/etc/cloudflared/token`, and triggers `cloudflared`.
- The operator never needs to manually generate, copy, or expose `CLOUDFLARED_TUNNEL_TOKEN`.
