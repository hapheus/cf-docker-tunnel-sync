# Cloudflare Tunnel Sync

`hapheus/cf-tunnel-sync` discovers labeled Docker containers and keeps a Cloudflare Zero Trust Tunnel, its ingress rules, and the corresponding proxied CNAME records in sync.

The image is the **core sync service**. Its unauthenticated API listens on port `8090` and is intended to stay inside the Docker network. Use the optional [`hapheus/cf-tunnel-dashboard`](https://hub.docker.com/r/hapheus/cf-tunnel-dashboard) image when a protected web UI is needed.

The `latest` and `0.1.0` tags are multi-architecture images for Linux `amd64` and `arm64`.

> **Requirements:** The domain must be managed by Cloudflare (its DNS nameservers point to Cloudflare). It may be registered with any registrar. The API token needs Account / Cloudflare Tunnel / Edit, Zone / Zone / Read, and Zone / DNS / Edit permissions.

Source code and complete documentation: [github.com/hapheus/cf-docker-tunnel-sync](https://github.com/hapheus/cf-docker-tunnel-sync)

## Quick start

Create a `.env` file:

```env
DOMAIN_NAME=example.com
CLOUDFLARE_API_TOKEN=replace_with_a_cloudflare_api_token
CLOUDFLARE_TUNNEL_NAME=cf-docker-tunnel-sync
```

Then create `docker-compose.yml`:

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    restart: always
    command: tunnel --no-autoupdate run --token-file /etc/cloudflared/token
    volumes:
      - cf_token_data:/etc/cloudflared
    networks:
      - cf-tunnel-net
    extra_hosts:
      - "host.docker.internal:host-gateway"

  cf-tunnel-sync:
    image: hapheus/cf-tunnel-sync:latest
    container_name: cf-tunnel-sync
    restart: always
    environment:
      - CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}
      - DOMAIN_NAME=${DOMAIN_NAME}
      - CLOUDFLARE_TUNNEL_NAME=${CLOUDFLARE_TUNNEL_NAME:-cf-docker-tunnel-sync}
      - POLL_INTERVAL=30
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - cf_token_data:/etc/cloudflared
    expose:
      - "8090"
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
    driver: bridge

volumes:
  cf_token_data:
```

Start it with:

```bash
docker compose up -d
```

On the first sync, the service creates or reuses the named Cloudflare Tunnel, writes its connector token to the shared volume, and restarts the `cloudflared` container if the token changed.

## Expose a Docker service

Add the labels below to a container in the same `cf-tunnel-net` network:

```yaml
services:
  my-app:
    image: nginx:alpine
    labels:
      - "cf.tunnel.hostname=app.${DOMAIN_NAME}"
      - "cf.tunnel.port=80"
    networks:
      - cf-tunnel-net
```

`cf.tunnel.hostname` is the public hostname and `cf.tunnel.port` is the container's internal port. Alternatively, use `cf.tunnel.service` with a complete target URL, for example `http://host.docker.internal:8080`, for a host service. The `extra_hosts` entry on `cloudflared` above enables that hostname on Linux hosts.

> The sync service deletes CNAME records that point to its tunnel but no longer belong to a labeled container. Do not manually point unrelated records at this tunnel.

## Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token. | Required |
| `DOMAIN_NAME` | Cloudflare zone name. | Required |
| `CLOUDFLARE_TUNNEL_NAME` | Tunnel name to create or reuse. | `cf-docker-tunnel-sync` |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID; avoids account auto-discovery. | Auto-discovered |
| `POLL_INTERVAL` | Interval between syncs, in seconds. | `30` |

## Optional dashboard

The core API deliberately has no authentication. Do not publish port `8090` to the host or expose the core container with tunnel labels. For a browser UI with optional Basic Authentication, deploy [`hapheus/cf-tunnel-dashboard`](https://hub.docker.com/r/hapheus/cf-tunnel-dashboard) on the same network.
