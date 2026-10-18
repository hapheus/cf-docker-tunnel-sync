# 🚀 Example 01: Quickstart Single Stack

This is the simplest, complete working setup of `cf-docker-tunnel-sync`. It runs the sync controller, the Cloudflare connector daemon (`cloudflared`), and a demo `whoami` service all within a single `docker-compose.yml`.

---

## What It Does

1. **`cf-tunnel-sync` (Control Plane):** Discovers running containers, contacts the Cloudflare API, provisions the tunnel named `quickstart-tunnel`, generates the tunnel credentials into the shared volume `/etc/cloudflared/token`, and synchronizes DNS CNAME records.
2. **`cloudflared` (Data Plane):** Starts once `cf-tunnel-sync` is healthy, reads the token from `/etc/cloudflared/token`, and establishes the encrypted outbound tunnel connection to Cloudflare edge.
3. **`whoami` (Demo App):** Connects to `cf-tunnel-net` with two labels. `cf-tunnel-sync` automatically creates `whoami.example.com` routing to `http://whoami:80`.

---

## How to Run

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` with your Cloudflare API token and root domain:
   ```env
   CLOUDFLARE_API_TOKEN=your_token_here
   DOMAIN_NAME=example.com
   ```
3. Start the stack:
   ```bash
   docker compose up -d
   ```
4. Verify by curling your new subdomain:
   ```bash
   curl -I https://whoami.example.com
   ```
