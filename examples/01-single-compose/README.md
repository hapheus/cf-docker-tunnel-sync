# Example 01: All-In-One Single Compose Stack

This example demonstrates the simplest possible deployment: running `cloudflared`, `cf-tunnel-sync` (with its native **embedded status dashboard**), and an application service inside a **single `docker-compose.yml` file**.

---

## 🎯 When to Use This
- Quickstart evaluations and proof-of-concept setups.
- Standalone host servers where all services reside in one Compose project.
- Homelabs looking for a self-contained, turnkey Cloudflare Tunnel setup without managing separate gateway networks.

---

## 🏗️ Architecture Overview

```text
                 Internet (HTTPS)
                        │
                        ▼
             Cloudflare Edge Network
                        │
                        ▼ (Zero Trust Encrypted Tunnel)
           ┌─────────────────────────────┐
           │         cloudflared         │
           └──────────────┬──────────────┘
                          │ (Docker network: cf-tunnel-net)
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
┌───────────────┐                   ┌───────────────┐
│ cf-tunnel-sync│                   │    my-app     │
│ (Embedded UI: │                   │ (Port 80 via  │
│  Port 8090 -> │                   │  cf.tunnel.*  │
│  Host: 8080)  │                   │  labels)      │
└───────┬───────┘                   └───────────────┘
        │
        ▼ (Event stream)
/var/run/docker.sock
```

- **Single Container Engine & UI:** `cf-tunnel-sync` runs both the event-driven synchronization engine and the FastAPI web dashboard internally on port `8090` (mapped to host port `8080`). No external Nginx container is required.
- **Fail-Closed Security:** Dashboard authentication is enabled by default (`DASHBOARD_AUTH_ENABLED=true`). If credentials are empty or unconfigured, access returns HTTP `401 Unauthorized`.
- **Automatic Cleanup:** When containers stop, Cloudflare Tunnel ingress rules are updated immediately, while DNS CNAME records are gracefully tombstoned for 300 seconds to eliminate DNS flapping during restarts.

---

## 🚀 How to Run

1. **Copy the environment template:**
   ```bash
   cp .env.example .env
   ```

2. **Configure your Cloudflare credentials & domain:**
   Edit `.env` and set:
   - `DOMAIN_NAME`: Your root domain registered on Cloudflare (e.g., `example.com`).
   - `CLOUDFLARE_API_TOKEN`: Token with `Zone:Read`, `Zone:DNS:Edit`, and `Account:Tunnel:Edit`.
   - `CLOUDFLARE_TUNNEL_NAME`: Tunnel name (defaults to `single-stack-tunnel`).
   - `DASHBOARD_USERNAME` & `DASHBOARD_PASSWORD`: Basic Auth credentials to secure the web dashboard.

3. **Start the stack:**
   ```bash
   docker compose up -d
   ```

4. **Access your services:**
   - **Embedded Status Dashboard:** Open `http://<your-host-ip>:8080` in your browser (authenticates via `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`).
   - **Application:** Within ~10-30 seconds, `cf-tunnel-sync` automatically creates the tunnel, configures Cloudflare edge ingress, and adds a proxied CNAME record for `app.<yourdomain.com>`. Access your application at `https://app.<yourdomain.com>`.
