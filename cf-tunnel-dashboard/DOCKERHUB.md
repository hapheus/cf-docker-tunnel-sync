# Cloudflare Tunnel Dashboard (`hapheus/cf-tunnel-dashboard`)

`hapheus/cf-tunnel-dashboard` is an optional, hardened Nginx frontend for [`hapheus/cf-tunnel-sync`](https://hub.docker.com/r/hapheus/cf-tunnel-sync). It serves a responsive management dashboard and proxies `/api/*` requests to the sync backend without requiring direct Docker socket access or Cloudflare API tokens.

> [!NOTE]
> The sync backend (`cf-tunnel-sync`) already includes an embedded dashboard on internal port 8090. This companion container is optional, designed for users who want a dedicated Nginx reverse proxy layer and separate Basic Auth boundary.

---

## Quick Start with Docker Compose

Add `cf-tunnel-dashboard` to your existing `cf-tunnel-net` gateway stack:

```yaml
services:
  cf-tunnel-dashboard:
    image: hapheus/cf-tunnel-dashboard:latest
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:80"
    environment:
      DASHBOARD_AUTH_ENABLED: "true"
      DASHBOARD_USERNAME: ${DASHBOARD_USERNAME:-admin}
      DASHBOARD_PASSWORD: ${DASHBOARD_PASSWORD}
      SYNC_BACKEND_HOST: cf-tunnel-sync
      SYNC_BACKEND_PORT: "8090"
    networks:
      - cf-tunnel-net

networks:
  cf-tunnel-net:
    external: true
```

Start the service and open `http://localhost:8080` in your browser.

---

## Configuration Reference

| Variable | Default | Description |
| --- | :---: | --- |
| `DASHBOARD_AUTH_ENABLED` | `true` | Enables HTTP Basic Authentication (`true` or `false`). |
| `DASHBOARD_USERNAME` | — | HTTP Basic Auth username (falls back to legacy `BASIC_AUTH_USERNAME`). |
| `DASHBOARD_PASSWORD` | — | HTTP Basic Auth password (falls back to legacy `BASIC_AUTH_PASSWORD`). |
| `SYNC_BACKEND_HOST` | `cf-tunnel-sync` | Hostname of the running `cf-tunnel-sync` container on the shared network. |
| `SYNC_BACKEND_PORT` | `8090` | Internal HTTP API port exposed by the backend container. |

> [!IMPORTANT]
> If `DASHBOARD_AUTH_ENABLED` is `true` and no credentials are provided, the container entrypoint fails safely and exits to prevent unauthenticated public exposure.

---

## Security & Operational Notes

- **Localhost Binding:** In the example above, the port is bound to `127.0.0.1:8080` to prevent unintended LAN/WAN exposure. For remote access, route through an encrypted HTTPS reverse proxy or Cloudflare Access.
- **Health Checks:** The `/health` endpoint checks local Nginx process health; backend synchronization status is reflected within the dashboard UI.
- **Access Labels:** Status labels displayed in the UI are informational metadata and do not replace Cloudflare Access authorization policies.

---

## Resources & Links

- **GitHub Repository:** [hapheus/cf-docker-tunnel-sync](https://github.com/hapheus/cf-docker-tunnel-sync)
- **Backend Sync Container:** [`hapheus/cf-tunnel-sync`](https://hub.docker.com/r/hapheus/cf-tunnel-sync)
- **API Documentation:** [docs/api.md](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/api.md)
- **Security Guide:** [docs/security.md](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/security.md)
