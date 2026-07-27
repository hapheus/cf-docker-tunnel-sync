# Cloudflare Tunnel Dashboard

`hapheus/cf-tunnel-dashboard` is the optional web UI for [`hapheus/cf-tunnel-sync`](https://hub.docker.com/r/hapheus/cf-tunnel-sync). It proxies the core service's internal API and protects the UI with Basic Authentication by default.

The image is a separate, lightweight Nginx container. It requires a running `cf-tunnel-sync` container reachable as `cf-tunnel-sync:8090` on the same Docker network. It does not manage Cloudflare tunnels or DNS by itself.

Source code and complete documentation: [github.com/hapheus/cf-docker-tunnel-sync](https://github.com/hapheus/cf-docker-tunnel-sync)

## Add the dashboard

Add this service to the Compose project that already runs `cf-tunnel-sync`:

```yaml
services:
  cf-tunnel-dashboard:
    image: hapheus/cf-tunnel-dashboard:latest
    container_name: cf-tunnel-dashboard
    restart: always
    environment:
      - DASHBOARD_AUTH_ENABLED=${DASHBOARD_AUTH_ENABLED:-true}
      - BASIC_AUTH_USERNAME=${BASIC_AUTH_USERNAME:-}
      - BASIC_AUTH_PASSWORD=${BASIC_AUTH_PASSWORD:-}
    ports:
      - "${DASHBOARD_BIND_ADDRESS:-0.0.0.0}:${DASHBOARD_PORT:-8080}:80"
    networks:
      - cf-tunnel-net
    depends_on:
      cf-tunnel-sync:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://127.0.0.1/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 2s
```

Set secure credentials in `.env`:

```env
DASHBOARD_AUTH_ENABLED=true
BASIC_AUTH_USERNAME=choose_a_username
BASIC_AUTH_PASSWORD=choose_a_long_random_password
DASHBOARD_BIND_ADDRESS=0.0.0.0
DASHBOARD_PORT=8080
```

Start or update the stack:

```bash
docker compose up -d
```

Open `http://your-server-ip:8080` and sign in with the configured credentials.

## Security

Authentication is enabled by default. When `DASHBOARD_AUTH_ENABLED=true`, the dashboard refuses to start unless both `BASIC_AUTH_USERNAME` and `BASIC_AUTH_PASSWORD` are set.

For a trusted, access-controlled network only, authentication can be disabled:

```env
DASHBOARD_AUTH_ENABLED=false
```

To make the UI accessible only from the Docker host, set `DASHBOARD_BIND_ADDRESS=127.0.0.1`. The health endpoint at `/health` is intentionally unauthenticated for container health checks.

## Optional Cloudflare Tunnel access

The dashboard is not exposed through the Cloudflare Tunnel by default. If remote access is intentional, add these labels to the dashboard service:

```yaml
labels:
  - "cf.tunnel.hostname=tunnel-sync.${DOMAIN_NAME}"
  - "cf.tunnel.port=80"
```

Keep Basic Authentication enabled and consider placing a Cloudflare Access policy in front of the hostname.
