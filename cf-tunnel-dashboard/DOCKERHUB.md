# Cloudflare Tunnel dashboard

`hapheus/cf-tunnel-dashboard` is an optional Nginx frontend for [`hapheus/cf-tunnel-sync`](https://hub.docker.com/r/hapheus/cf-tunnel-sync). It serves a dashboard and proxies `/api/*` to the backend. It needs neither Docker socket access nor Cloudflare credentials.

![Dashboard preview](https://raw.githubusercontent.com/hapheus/cf-docker-tunnel-sync/main/docs/screenshots/dashboard-preview.png)

The sync backend also serves an embedded dashboard. Choose one frontend arrangement; the companion container is not required for synchronization.

## Configure

| Variable | Default | Effect |
| --- | --- | --- |
| `DASHBOARD_AUTH_ENABLED` | `true` | Accepts `true` or `false`; enables frontend Basic Auth. |
| `DASHBOARD_USERNAME` | Empty | Recommended dashboard basic auth username. Falls back to `BASIC_AUTH_USERNAME`. |
| `DASHBOARD_PASSWORD` | Empty | Recommended dashboard basic auth password. Falls back to `BASIC_AUTH_PASSWORD`. |
| `BASIC_AUTH_USERNAME` | Empty | Legacy alias for `DASHBOARD_USERNAME` (deprecated; will be removed in a future release). |
| `BASIC_AUTH_PASSWORD` | Empty | Legacy alias for `DASHBOARD_PASSWORD` (deprecated; will be removed in a future release). |
| `SYNC_BACKEND_HOST` | `cf-tunnel-sync` | Backend Docker hostname. |
| `SYNC_BACKEND_PORT` | `8090` | Backend internal API port. |

With auth enabled and missing credentials, the entrypoint exits instead of starting Nginx. Configure the backend's authentication deliberately as well. The frontend proxy does not remove the need to protect a separately published backend.

## Add to an existing gateway

This fragment assumes the backend is named `cf-tunnel-sync` and already reachable on `cf-tunnel-net`. Supply your own password through the Compose environment:

```yaml
services:
  cf-tunnel-dashboard:
    image: hapheus/cf-tunnel-dashboard:latest
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:80"
    environment:
      DASHBOARD_AUTH_ENABLED: "true"
      BASIC_AUTH_USERNAME: admin
      BASIC_AUTH_PASSWORD: ${BASIC_AUTH_PASSWORD}
      SYNC_BACKEND_HOST: cf-tunnel-sync
      SYNC_BACKEND_PORT: "8090"
    networks:
      - cf-tunnel-net

networks:
  cf-tunnel-net:
    external: true
```

Recreate the service and visit `http://localhost:8080`. Select a different host port if one is already in use. For remote access, configure a deliberate protected route; Basic Auth over unencrypted HTTP is not suitable for an untrusted network.

The frontend's public `/health` reports Nginx availability, not backend sync or application health. Other status values reflect backend observations, not a separate reachability probe. An Access metadata label does not configure a Cloudflare Access policy.

[Quickstart](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/QUICKSTART.md) · [API](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/api.md) · [Security](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/security.md)
