# 10-Minute Canonical Quickstart Guide

Get your self-hosted Docker services securely exposed through Cloudflare Tunnels in under 10 minutes with automated ingress routing, automated DNS CNAME synchronization, and zero open inbound ports on your firewall.

> 💡 **Simplicity First — Headless by Design**:  
> `cf-tunnel-sync` is primarily an autonomous, set-and-forget background daemon. It runs silently in the background, continuously syncing Docker labels to Cloudflare Tunnels without requiring any exposed host ports or web UI.  
> 
> Visual status monitoring is **100% optional** and can be added at any time via the companion container `hapheus/cf-tunnel-dashboard` or by exposing the internal status port.

---

## ⚡ Prerequisites & Cloudflare Identifiers

Before beginning, ensure you have:
1. **Docker Engine & Docker Compose v2+** installed on your host.
2. A **Domain Name** active on Cloudflare (e.g., `example.com`).
3. A **Scoped Cloudflare API Token**.

### Cloudflare Identifiers Explained

| Identifier | Where to Find It | Required? |
| :--- | :--- | :--- |
| **API Token** | Cloudflare Dashboard → Profile → API Tokens. | **Yes** (Essential) |
| **Tunnel Name** | You choose any name (e.g. `my-tunnel`). Auto-created on startup. | **Yes** (Essential) |
| **Domain Name** | Your root domain zone in Cloudflare (e.g. `example.com`). | **Yes** (Essential) |
| **Account ID** | Cloudflare Dashboard → select your domain under **Websites** → right sidebar. | **Optional** (auto-detected from domain zone or API token) |
| **Zone ID** | Cloudflare Dashboard → right sidebar under Account ID. | **Optional** (auto-discovered via `Zone:Read` permission) |
| **Tunnel ID** | Cloudflare Dashboard → Zero Trust → Networks → Tunnels. | **Optional** (auto-created if `CLOUDFLARE_TUNNEL_NAME` is used) |

---

## Step 1: Obtain Your Cloudflare API Token

1. Navigate to the [Cloudflare API Tokens Dashboard](https://dash.cloudflare.com/profile/api-tokens).
2. Click **Create Token** → **Create Custom Token**.
3. Configure the following 3 required permissions:
   - `Account` | `Cloudflare Tunnel` | `Edit` (Scoped to your account)
   - `Zone` | `DNS` | `Edit` (Scoped to your target zone or All zones)
   - `Zone` | `Zone` | `Read` (Scoped to your target zone or All zones)
4. Copy the generated token string.

---

## Step 2: Deploy the Gateway Stack

Create a working directory and a `.env` file containing only the **Essential Three** settings:

```bash
mkdir -p ~/cf-tunnel && cd ~/cf-tunnel
cat << 'EOF' > .env
CLOUDFLARE_API_TOKEN=your_cloudflare_api_token_here
CLOUDFLARE_TUNNEL_NAME=my-homelab-tunnel
DOMAIN_NAME=example.com
EOF
```

Create your headless gateway `docker-compose.yml`:

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    restart: unless-stopped
    command: tunnel --no-autoupdate run --token-file /etc/cloudflared/token
    volumes:
      - cf_token_data:/etc/cloudflared
    networks:
      - cf-tunnel-net
    depends_on:
      cf-tunnel-sync:
        condition: service_healthy

  cf-tunnel-sync:
    image: hapheus/cf-tunnel-sync:latest
    container_name: cf-tunnel-sync
    restart: unless-stopped
    environment:
      - CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}
      - CLOUDFLARE_TUNNEL_NAME=${CLOUDFLARE_TUNNEL_NAME:-cf-docker-tunnel-sync}
      - DOMAIN_NAME=${DOMAIN_NAME}
      - CF_NETWORK_NAME=cf-tunnel-net
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - cf_token_data:/etc/cloudflared
    networks:
      - cf-tunnel-net
    healthcheck:
      test: ["CMD", "python", "healthcheck.py"]
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

Start the gateway:
```bash
docker compose up -d
```

---

## Step 3: Run Non-Mutating Preflight Validation (Optional)

Before synchronizing live containers, verify your Docker socket access, token permissions, and Cloudflare reachability without making any mutations:

```bash
docker compose run --rm cf-tunnel-sync python app.py --preflight
```

Output:
```text
==================================================
🔍 Starting Non-Mutating Preflight Validation
==================================================
✅ [PREFLIGHT PASS] Docker daemon connected (Version: 26.1.0).
✅ [PREFLIGHT PASS] Cloudflare API token verified and active.
✅ [PREFLIGHT PASS] Cloudflare Zone verified for 'example.com' (Zone ID: abc123...).
✅ [PREFLIGHT PASS] Cloudflare Tunnel 'my-homelab-tunnel' inspected.
✅ [PREFLIGHT PASS] Network topology inspected.
==================================================
🎉 [PREFLIGHT SUCCESS] All preflight checks passed successfully. Zero mutations performed.
```

> ℹ️ **Preflight vs. Standard Startup Lifecycle**:  
> Preflight runs in **read-only mode** and will never create tunnels or mutate DNS records. When you start `cf-tunnel-sync` normally, it automatically creates the named tunnel if it does not yet exist and registers ingress rules for all labeled containers.

---

## Step 4: Expose an Existing Service

Connect any existing application service to `cf-tunnel-net` and add routing labels:

### Literal Before & After Compose Diff

```diff
 services:
   whoami:
     image: traefik/whoami:latest
-    ports:
-      - "8080:80"
+    networks:
+      - default
+      - cf-tunnel-net
+    labels:
+      - "cf.tunnel.hostname=whoami.example.com"
+      - "cf.tunnel.port=80"

+networks:
+  cf-tunnel-net:
+    external: true
```

> ⚠️ **Container Port vs. Host Port**:  
> Set `cf.tunnel.port` to the **internal port** your application listens on inside its container (`80`). Host port publishing (`ports:`) is no longer required and can be removed completely.

Deploy your updated service:
```bash
docker compose up -d
```

---

## Step 5: Fast 2-Minute Verification Path

Verify end-to-end functionality with three quick steps:

### 1. Check Container Health
```bash
docker compose ps
```

### 2. Inspect Sync Logs
```bash
docker compose logs -f cf-tunnel-sync
```
*Look for:*
```text
INFO: 🚀 Discovered container whoami (whoami.example.com -> http://whoami:80)
INFO: ✅ Cloudflare Tunnel ingress configuration updated
INFO: ✅ Cloudflare DNS CNAME created: whoami.example.com -> <tunnel-id>.cfargotunnel.com
```

### 3. Verify HTTPS Connectivity
```bash
curl -Iv https://whoami.example.com
```
*Look for HTTP 200 and Cloudflare response headers (`cf-ray`).*

---

## Step 6: Predictive Dry-Run & Safety Guardrails

### Dry-Run Mode
Preview changes without mutating Cloudflare:
```bash
docker compose run --rm -e DRY_RUN=true cf-tunnel-sync python app.py --dry-run
```

### Blast-Radius Protection
`cf-docker-tunnel-sync` includes automated circuit breaker protection:
- `MASS_DELETION_LIMIT=3`: Blocks runaway mass deletions if Docker restarts or multiple containers stop at once.
- If the limit is exceeded, sync immediately aborts, preserves Cloudflare routes untouched, and logs a safety warning.
- Set `ALLOW_MASS_DELETIONS=true` if intentionally decommissioning multiple services simultaneously.

---

## 📚 Related Documentation

- 🚀 **[Onboarding Existing Services](docs/onboarding.md)** — Step-by-step <10-minute guide to exposing existing Docker services.
- ⚙️ **[Configuration Reference](docs/configuration.md)** — Exhaustive environment variable specification and auto-discovery rules.
- 🏷️ **[Docker Labels Reference](docs/labels.md)** — All supported container labels, port precedence, and routing.
- 🔧 **[Troubleshooting Guide](docs/troubleshooting.md)** — Task-based diagnosis, error codes, and practical remedies.
- 📋 **[Support Matrix & Platform Limits](docs/support-matrix.md)** — Supported operating systems, Docker versions, and Cloudflare tiers.
- 🏆 **[Multi-Compose Production Walkthrough](examples/02-multi-compose/README.md)** — Independent gateway and multi-stack architecture.
- 🛡️ **[Security Architecture](docs/security.md)** — Docker socket isolation and credential protection.
