# Example 02: Multi-Compose Architecture (Flagship Gateway Pattern)

This is the **canonical production architecture** for self-hosters and teams running multiple containers or distinct `docker-compose.yml` stacks on a single Docker host.

Instead of running a separate Cloudflare tunnel inside every application stack, you run **one central gateway stack**. All application stacks join a shared internal Docker network (`cf-tunnel-net`) and configure labels to expose themselves securely through Cloudflare Zero Trust tunnels without opening any router ports or publishing host ports.

---

## 🏗️ Architecture Overview

```text
               Cloudflare Edge (HTTPS)
                         │
                         ▼
             [ cloudflared Tunnel Agent ]
                         ▲
                         │ (cf-tunnel-net bridge network)
         ┌───────────────┴───────────────┐
         │                               │
         ▼                               ▼
[ Gateway Stack ]              [ Application Stack ]
 - cloudflared                  - service-whoami (port 80)
 - cf-tunnel-sync                 Labels:
 - cf-tunnel-dashboard (optional)  - cf.tunnel.hostname=whoami.example.com
                                   - cf.tunnel.port=80
```

### Key Benefits
- **Zero Host Ports Required:** All ingress routes directly over Cloudflare Tunnel into Docker containers via the private bridge network.
- **Isolated Lifecycles:** Upgrade or restart individual services without tearing down the tunnel gateway.
- **Declarative Label Configuration:** New services are automatically registered with Cloudflare DNS and Tunnel routing upon starting.

---

## 📁 Directory Structure

```text
examples/02-multi-compose/
├── README.md                      # Flagship walkthrough (this guide)
├── gateway/                       # Central gateway stack
│   ├── .env.example               # Gateway environment variables
│   ├── docker-compose.yml         # Standard gateway (includes Web Dashboard)
│   ├── docker-compose.headless.yml# Minimal headless gateway (zero host ports)
│   └── README.md
├── service-whoami/                # Sample application stack (Whoami)
│   ├── .env.example
│   ├── docker-compose.yml
│   └── README.md
├── service-api/                   # Optional sample API stack
└── service-website/               # Optional sample static site stack
```

---

## 📋 Prerequisites

Before beginning, ensure you have:
1. **Docker Engine & Docker Compose v2** installed on your host.
2. A domain registered and active on Cloudflare (e.g., `example.com`).
3. A Cloudflare API Token with the following permissions:
   - **Zone : DNS : Edit** (All zones or specific zone)
   - **Account : Cloudflare Tunnel : Edit** (All accounts)
   - **Zone : Zone : Read** (All zones)

---

## 🚀 Step-by-Step Walkthrough

### Step 1: Start the Central Gateway

Navigate to the `gateway/` directory:

```bash
cd examples/02-multi-compose/gateway
```

Create and configure your `.env` file from the provided template:

```bash
cp .env.example .env
```

Edit `.env` with your domain and Cloudflare API token:
```env
DOMAIN_NAME=example.com
CLOUDFLARE_API_TOKEN=your_cf_api_token_here
CLOUDFLARE_TUNNEL_NAME=gateway-tunnel
CF_NETWORK_NAME=cf-tunnel-net
```

Run non-mutating preflight validation to verify permissions and Docker connectivity before starting:

```bash
docker compose run --rm cf-tunnel-sync --preflight
```

Launch the gateway stack:

* **Option A: Headless Gateway (Recommended for Production - Zero Host Ports):**
  ```bash
  docker compose -f docker-compose.headless.yml up -d
  ```

* **Option B: Standard Gateway (with companion Web Dashboard on port 8080):**
  ```bash
  docker compose up -d
  ```

This creates the shared `cf-tunnel-net` Docker network, creates the Cloudflare Tunnel credentials, and begins monitoring the Docker socket.

---

### Step 2: Deploy the Application Service (`service-whoami`)

In a new terminal window or after the gateway is up, navigate to the `service-whoami` directory:

```bash
cd ../service-whoami
```

Create and configure its `.env` file:

```bash
cp .env.example .env
```

Ensure `DOMAIN_NAME` matches your root domain:
```env
DOMAIN_NAME=example.com
SUBDOMAIN=whoami
```

Start the application container:

```bash
docker compose up -d
```

The `service-whoami` stack joins the existing `cf-tunnel-net` network via `external: true`:
```yaml
services:
  whoami:
    image: traefik/whoami:latest
    restart: always
    labels:
      - "cf.tunnel.hostname=${SUBDOMAIN:-whoami}.${DOMAIN_NAME}"
      - "cf.tunnel.port=80"
    networks:
      - cf-tunnel-net

networks:
  cf-tunnel-net:
    external: true
```

---

### Step 3: Verify Status & Expected Logs

Check the sync controller logs in the gateway stack:

```bash
docker compose -f ../gateway/docker-compose.yml logs -f cf-tunnel-sync
```

You should see log output similar to:

```text
INFO:cf-tunnel-sync:🔍 Discovered container 'service-whoami-whoami-1' with label cf.tunnel.hostname='whoami.example.com'
INFO:cf-tunnel-sync:🔄 Syncing ingress rule: whoami.example.com -> http://service-whoami-whoami-1:80
INFO:cf-tunnel-sync:✅ Cloudflare Tunnel ingress configuration updated successfully.
INFO:cf-tunnel-sync:🌐 Provisioning Cloudflare DNS CNAME: whoami.example.com -> <tunnel-id>.cfargotunnel.com
INFO:cf-tunnel-sync:✅ DNS CNAME created/verified for whoami.example.com.
INFO:cf-tunnel-sync:🟢 Container 'service-whoami-whoami-1' is live and routable!
```

Verify public HTTPS access using `curl` or your web browser:

```bash
curl -I https://whoami.example.com
```

Expected output:
```text
HTTP/2 200
content-type: text/plain; charset=utf-8
server: cloudflare
...
```

---

### Step 4: Cleanup & Teardown

To shut down the demo application cleanly:

```bash
# In service-whoami/
docker compose down
```
Notice in the gateway logs that `cf-tunnel-sync` automatically cleans up the tunnel ingress and DNS CNAME record.

To shut down the central gateway stack:

```bash
# In gateway/
docker compose down -v
# Or for headless:
docker compose -f docker-compose.headless.yml down -v
```
