# Two gateways on one Docker host

Use independent gateways for two Cloudflare zones/accounts. This example provides [personal-gateway](personal-gateway/README.md) and [business-gateway](business-gateway/README.md), each with a sync service, connector, and companion dashboard. You need Docker Compose v2, the two zones, and [scoped tokens](../../docs/cloudflare-permissions.md) for their respective accounts.

## Configure

From this directory:

```bash
cp personal-gateway/.env.example personal-gateway/.env
cp business-gateway/.env.example business-gateway/.env
```

Edit both files privately. Replace the example domains, tokens, and dashboard passwords. Account IDs are optional and forwarded when set.

| Setting | Personal example | Business example |
| --- | --- | --- |
| Domain placeholder | `example.com` | `example.net` |
| Tunnel name | `personal-tunnel` | `company-tunnel` |
| Connector container name | `personal-cloudflared` | `business-cloudflared` |
| Gateway network | `cf-tunnel-net-personal` | `cf-tunnel-net-business` |
| Dashboard host port | `8080` | `8081` |

The sync services use their unique `CLOUDFLARED_CONTAINER_NAME` for network checks and restart targeting. Keep these names unique on the host. Existing installations adopting these files recreate connector containers under these explicit names; the normal project-scoped token volumes are retained.

Run each directory as its own Compose project. Their token volumes are then separate even though both files call the volume `cf_token_data`. Do not use the same `-p`/`COMPOSE_PROJECT_NAME` override for both.

## Start

```bash
cd personal-gateway
docker compose up -d
docker compose logs --tail=50 cf-tunnel-sync cloudflared
cd ../business-gateway
docker compose up -d
docker compose logs --tail=50 cf-tunnel-sync cloudflared
```

Both connectors wait for their own nonempty token file and sync health endpoint. The examples explicitly poll every 30 seconds in addition to Docker events; this overrides the application's 900-second default.

The environment templates publish dashboards only on `127.0.0.1`, at `http://localhost:8080` and `http://localhost:8081`. Log in with each configured frontend credential. Existing environment files without `DASHBOARD_BIND_ADDRESS` retain the Compose fallback of `0.0.0.0`; set the bind address deliberately. Backend APIs are not host-published, but containers on their networks can reach them.

## Attach an application

For a personal-domain HTTP service, create an application Compose file such as:

```yaml
services:
  web:
    image: nginx:alpine
    restart: unless-stopped
    labels:
      cf.tunnel.hostname: app.example.com
      cf.tunnel.port: "80"
      cf.tunnel.name: personal-tunnel
    networks:
      - gateway

networks:
  gateway:
    name: cf-tunnel-net-personal
    external: true
```

Replace the domain, network, and tunnel name with your values. For the business gateway, use its domain, network, and `company-tunnel` instead. Recreate the application and check its public response:

```bash
docker compose up -d
curl -I https://app.example.com
```

Domain/tunnel filtering selects the intended controller; network separation provides routing isolation, not per-user authorization. Configure private application authentication separately. See [labels](../../docs/labels.md) and [current safety limitations](../../docs/architecture-and-safety.md#current-limitations).

## Inspect and stop

From either gateway directory:

```bash
docker compose exec cf-tunnel-sync python app.py --preflight
docker compose down
```

Preflight is non-mutating but does not prove all permissions or reachability. Stop each gateway from its own directory. `down` retains token volumes and Cloudflare resources; use [operations](../../docs/operations.md) for full cleanup.
