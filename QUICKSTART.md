# Quickstart

Set up a headless gateway and an HTTP demo application. You need Docker Compose v2, a domain zone active on Cloudflare, a [scoped API token](docs/cloudflare-permissions.md), and outbound connectivity for `cloudflared`.

Choose a dedicated tunnel name. Startup creates a missing tunnel and modifies ingress/DNS; this is a live setup procedure. Read [current limitations](docs/architecture-and-safety.md#current-limitations) first if you already have tunnel rules or DNS records.

## 1. Configure the gateway

Create a working directory:

```bash
mkdir -p ~/cf-tunnel
cd ~/cf-tunnel
```

Create `.env` with your own token and domain. Keep it private and out of version control:

```dotenv
CLOUDFLARE_API_TOKEN=replace-with-your-scoped-token
CLOUDFLARE_TUNNEL_NAME=homelab-gateway
DOMAIN_NAME=example.com
```

Create `docker-compose.yml`:

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
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
    restart: unless-stopped
    environment:
      CLOUDFLARE_API_TOKEN: ${CLOUDFLARE_API_TOKEN}
      CLOUDFLARE_TUNNEL_NAME: ${CLOUDFLARE_TUNNEL_NAME}
      DOMAIN_NAME: ${DOMAIN_NAME}
      CF_NETWORK_NAME: cf-tunnel-net
      DASHBOARD_ENABLED: "false"
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
      start_period: 5s

networks:
  cf-tunnel-net:
    name: cf-tunnel-net
    driver: bridge

volumes:
  cf_token_data:
```

This creates the gateway network and shares the generated token with the connector. No ports are published. The Docker socket is privileged even with `:ro`; see [security](docs/security.md). For repeatable deployment, replace floating tags with selected [versions or digests](docs/release-security.md).

Start and inspect it:

```bash
docker compose up -d
docker compose logs --tail=50 cf-tunnel-sync cloudflared
```

The healthcheck does not wait for a token or verify connector connectivity. On first boot the connector may start before initialization finishes; inspect both logs and restart `cloudflared` after initialization if necessary.

## 2. Start an application stack

Create a separate directory and Compose file. Replace `whoami.example.com` with a hostname under your configured domain:

```yaml
services:
  whoami:
    image: traefik/whoami:latest
    restart: unless-stopped
    networks:
      - cf-tunnel-net
    labels:
      cf.tunnel.hostname: whoami.example.com
      cf.tunnel.port: "80"

networks:
  cf-tunnel-net:
    external: true
```

Run `docker compose up -d` from that application's directory. The gateway network must exist first. Current discovery does not require `cf.tunnel.enable`; see [label selection](docs/labels.md#hostname-and-selection-details).

## 3. Verify

From a client that can access your public domain:

```bash
curl -I https://whoami.example.com
```

The demo normally returns HTTP 200. If it fails, inspect gateway/connector logs and follow [troubleshooting](docs/troubleshooting.md). A real private application also needs application authentication or a separately configured Cloudflare Access policy; an Access metadata label does not protect it.

## Inspect without making configuration changes

From the gateway directory, after its container is running:

```bash
docker compose exec cf-tunnel-sync python app.py --preflight
```

Preflight reads Docker and Cloudflare but does not create resources. It does not prove all write permissions or public reachability. `DRY_RUN=true` is not a fully non-mutating substitute because initialization occurs before its guard.

## Next steps

- [Add an existing application](docs/onboarding.md).
- [Enable the dashboard or configure API authentication](docs/configuration.md#dashboard-api-and-logs).
- [Inspect status and metrics or remove a route](docs/operations.md).
- [Browse all documentation](docs/README.md).
