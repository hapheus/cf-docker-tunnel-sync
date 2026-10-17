# 10-Minute Canonical Quickstart Guide

Get your self-hosted Docker services securely exposed through Cloudflare Tunnels in under 10 minutes with automated ingress routing, automated DNS CNAME synchronization, and zero open inbound ports on your firewall.

---

## ⚡ Prerequisites

Before beginning, ensure you have:
1. **Docker Engine & Docker Compose v2+** installed on your host.
2. A **Domain Name** active on Cloudflare (e.g., `example.com`).
3. A **Cloudflare API Token** with the following scoped permissions:
   - **Zone -> DNS -> Edit**
   - **Account -> Cloudflare Tunnel -> Edit**

---

## Step 1: Obtain Your Cloudflare API Token

1. Navigate to the [Cloudflare API Tokens Dashboard](https://dash.cloudflare.com/profile/api-tokens).
2. Click **Create Token** -> **Create Custom Token**.
3. Configure the following permissions:
   - `Zone` | `DNS` | `Edit` (Scoped to your target zone or All zones)
   - `Account` | `Cloudflare Tunnel` | `Edit` (Scoped to your account)
4. Copy the generated token.

---

## Step 2: Create the Compose Stack

Create a working directory and a `.env` file:

```bash
mkdir -p ~/cf-tunnel && cd ~/cf-tunnel
cat << 'EOF' > .env
CLOUDFLARE_API_TOKEN=your_cloudflare_api_token_here
DOMAIN_NAME=example.com
CLOUDFLARE_TUNNEL_NAME=my-homelab-tunnel
EOF
```

Create `docker-compose.yml`:

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    restart: always
    command: tunnel --no-autoupdate --protocol auto run --token-file /etc/cloudflared/token
    volumes:
      - cf_token_data:/etc/cloudflared
    networks:
      - cf-tunnel-net
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      cf-tunnel-sync:
        condition: service_healthy

  cf-tunnel-sync:
    image: hapheus/cf-tunnel-sync:latest
    container_name: cf-tunnel-sync
    restart: always
    environment:
      - CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}
      - CLOUDFLARE_TUNNEL_NAME=${CLOUDFLARE_TUNNEL_NAME:-cf-docker-tunnel-sync}
      - DOMAIN_NAME=${DOMAIN_NAME}
      - CF_NETWORK_NAME=cf-tunnel-net
      - TOKEN_FILE_PATH=/etc/cloudflared/token
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - cf_token_data:/etc/cloudflared
    networks:
      - cf-tunnel-net
    ports:
      - "8090:8090"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://127.0.0.1:8090/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 2s

networks:
  cf-tunnel-net:
    name: cf-tunnel-net
    driver: bridge

volumes:
  cf_token_data:
```

---

## Step 3: Run Non-Mutating Preflight Validation (R01)

Before starting the daemon, execute the preflight check to verify connectivity, token validity, and tunnel configuration without performing any mutations:

```bash
docker compose run --rm cf-tunnel-sync python app.py --preflight
```

Or run via the `PREFLIGHT_ONLY=true` environment variable:

```bash
docker compose run --rm -e PREFLIGHT_ONLY=true cf-tunnel-sync
```

Output:
```text
==================================================
🔍 Starting Non-Mutating Preflight Validation (R01)
==================================================
✅ [PREFLIGHT PASS] Docker daemon connected (Version: 26.1.0).
✅ [PREFLIGHT PASS] Cloudflare API token verified and active.
✅ [PREFLIGHT PASS] Cloudflare Zone verified for 'example.com' (Zone ID: abc123...).
✅ [PREFLIGHT PASS] Cloudflare Tunnel 'my-homelab-tunnel' found (ID: tun-456...).
✅ [PREFLIGHT PASS] Network topology inspected (0 total containers, 0 tunneled services).
==================================================
🎉 [PREFLIGHT SUCCESS] All preflight checks passed successfully. Zero mutations performed.
```

If any check fails, actionable remedy guidance will be logged directly in the terminal.

---

## Step 4: Expose Your First Service

Add an application container to the compose stack or attach labels to any container sharing `cf-tunnel-net`:

```yaml
  whoami:
    image: traefik/whoami:latest
    container_name: whoami
    restart: always
    labels:
      - "cf.tunnel.hostname=whoami.example.com"
      - "cf.tunnel.port=80"
    networks:
      - cf-tunnel-net
```

Start the entire stack:

```bash
docker compose up -d
```

---

## Step 5: Truthful Diagnostics & Visual Status (R02)

Open `http://localhost:8090` in your browser.

The web dashboard and the `GET /api/status` endpoint evaluate a **6-stage diagnostic pipeline** for each service:
1. `LABEL_SYNTAX`: Validates RFC 1123 hostname and port formatting.
2. `TUNNEL_DOMAIN_MATCH`: Validates hostname against configured `DOMAIN_NAME`.
3. `NETWORK_TOPOLOGY`: Confirms shared Docker bridge network with `cloudflared`.
4. `CLOUDFLARE_INGRESS`: Confirms Cloudflare Tunnel remote configuration.
5. `CLOUDFLARE_DNS`: Confirms active CNAME record pointing to the tunnel target.
6. `ORIGIN_HEALTH`: Confirms origin container is running and healthy.

State integrity guarantee: Status will never report "Synced" if any upstream stage (1–5) fails. If ingress or DNS fails, status truthfully reports `Degraded` or `Failed`.

---

## Step 6: Predictive Dry-Run & ChangePlan API (R03)

Want to preview changes before applying them?
Run with `DRY_RUN=true`:

```bash
docker compose run --rm -e DRY_RUN=true cf-tunnel-sync python app.py --dry-run
```

Or query the ChangePlan API endpoint:

```bash
curl -s http://localhost:8090/api/change-plan | jq .
```

Response:
```json
{
  "plan_id": "4b2c129e-f001-49e0-8a12-88151dc3a123",
  "dry_run": true,
  "timestamp": 1729145545.12,
  "actions": [
    {
      "action": "CREATE",
      "resource": "INGRESS",
      "target": {
        "hostname": "whoami.example.com",
        "service": "http://whoami:80"
      },
      "reason": "New origin discovered in Docker container"
    },
    {
      "action": "CREATE",
      "resource": "DNS",
      "target": {
        "hostname": "whoami.example.com",
        "target_content": "tun-456.cfargotunnel.com"
      },
      "reason": "Missing DNS CNAME for active origin"
    }
  ],
  "summary": {
    "additions": 2,
    "updates": 0,
    "deletions": 0,
    "unmanaged_skipped": 0
  }
}
```

---

## Step 7: Blast-Radius & Deletion Guardrails (R04)

`cf-docker-tunnel-sync` includes automated safety trip protection:
- `MAX_DELETIONS_PER_SYNC=3`: Blocks runaway mass-deletions if Docker restarts or multiple containers stop simultaneously.
- If threshold is exceeded, sync immediately aborts, retains Cloudflare routes untouched, and flags `SAFETY_GUARD_TRIPPED` in `/api/status`.
- Set `ALLOW_MASS_DELETIONS=true` if performing an intentional large-scale decommissioning.
