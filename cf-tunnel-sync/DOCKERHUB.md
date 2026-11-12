# Cloudflare Tunnel Docker Synchronizer (`hapheus/cf-tunnel-sync`)

Automate Cloudflare Tunnel ingress routing and DNS CNAME records directly from Docker container labels.

The synchronizer acts as the **control plane** (managing configuration via the Cloudflare API), while the official [`cloudflare/cloudflared`](https://hub.docker.com/r/cloudflare/cloudflared) container acts as the **data plane** (routing encrypted tunnel traffic to your Docker network).

---

## Quick Start with Docker Compose

Run `cf-tunnel-sync` alongside `cloudflared`. Both containers share a dedicated Docker bridge network and a lightweight token volume (`cf_token_data`).

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:2025.5.0
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
      CLOUDFLARE_TUNNEL_NAME: ${CLOUDFLARE_TUNNEL_NAME:-homelab-tunnel}
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

---

## Exposing Applications

Attach your application container to `cf-tunnel-net` and specify the hostname and internal container port:

```yaml
services:
  my-app:
    image: nginx:alpine
    restart: unless-stopped
    networks:
      - cf-tunnel-net
    labels:
      cf.tunnel.hostname: app.example.com
      cf.tunnel.port: "80"

networks:
  cf-tunnel-net:
    external: true
```

No host port forwarding (e.g. `80:80` or `443:443`) is required. Traffic flows securely through Cloudflare's edge into the container.

---

## Core Environment Variables

| Variable | Required | Default | Description |
| --- | :---: | :---: | --- |
| `CLOUDFLARE_API_TOKEN` | **Yes** | — | Scoped Cloudflare API token with Zone DNS and Account Tunnel edit permissions. |
| `DOMAIN_NAME` | **Yes** | — | Your registered domain zone (e.g., `example.com`). |
| `CLOUDFLARE_TUNNEL_NAME` | **Yes** | — | Dedicated tunnel name (created automatically if missing). |
| `CLOUDFLARE_ACCOUNT_ID` | No | Auto-detected | Cloudflare Account ID (inferred from domain zone when omitted). |
| `CF_NETWORK_NAME` | No | `cf-tunnel-net` | Docker network name shared with the `cloudflared` connector. |
| `SYNC_FALLBACK_INTERVAL` | No | `900` | Fallback reconciliation interval in seconds (Docker events trigger instant syncs). |
| `MAX_DELETIONS_PER_SYNC`| No | `3` | Safety limit: prevents accidental mass deletion during sync cycles. |
| `DRY_RUN` | No | `false` | When `true`, logs planned changes without mutating Cloudflare API resources. |
| `DASHBOARD_ENABLED` | No | `false` | Enables the embedded status UI on internal port 8090. |

---

## Safety & Operational Notes

- **Preflight Inspection:** Run non-mutating checks without changing live resources:
  ```bash
  docker compose exec cf-tunnel-sync python app.py --preflight
  ```
- **Scoped API Tokens:** Never use a Global API Key. Use a token scoped to `Account: Cloudflare Tunnel: Edit` and `Zone: DNS: Edit`. See [Permissions Guide](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/cloudflare-permissions.md).
- **Socket Security:** The Docker socket mount (`/var/run/docker.sock`) grants root-equivalent host access. On untrusted environments, use the [Docker Socket Proxy example](https://github.com/hapheus/cf-docker-tunnel-sync/tree/main/examples/03-secure-socket-proxy).
- **Access Labels:** Labels like `cf.tunnel.access` display metadata in the UI only; they do not configure Cloudflare Access authorization policies.

---

## Resources & Links

- **GitHub Repository:** [hapheus/cf-docker-tunnel-sync](https://github.com/hapheus/cf-docker-tunnel-sync)
- **Detailed Quickstart:** [QUICKSTART.md](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/QUICKSTART.md)
- **Label Reference:** [docs/labels.md](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/labels.md)
- **Architecture & Safety Limits:** [docs/architecture-and-safety.md](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/architecture-and-safety.md)
- **Optional Web Dashboard Image:** [`hapheus/cf-tunnel-dashboard`](https://hub.docker.com/r/hapheus/cf-tunnel-dashboard)
