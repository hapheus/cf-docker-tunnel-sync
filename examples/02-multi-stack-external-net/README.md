# Separate gateway and application stacks

Use one external network to connect an independent application stack to `cloudflared`. You need Docker Compose v2, a Cloudflare zone, and a [scoped token](../../docs/cloudflare-permissions.md). The `traefik/whoami` web demo returns request details. PostgreSQL demonstrates a separate backend network; whoami itself does not connect to it.

Read [networking](../../docs/networking-guide.md) and [current safety limitations](../../docs/architecture-and-safety.md#current-limitations) before connecting existing services.

## Configure the two stacks

From this example's directory:

```bash
cp core-tunnel-stack/.env.example core-tunnel-stack/.env
cp app-stack-example/.env.example app-stack-example/.env
```

Edit both files privately. Replace the gateway token/domain and the demo database password. Set the **same** `DOMAIN_NAME` and `CF_NETWORK_NAME` in both directories. The optional gateway account ID is forwarded when configured.

Create the chosen external network once; substitute your configured name if different:

```bash
docker network create cf-tunnel-net
```

## Start a gateway variant

```bash
cd core-tunnel-stack
docker compose up -d
docker compose logs --tail=50 cf-tunnel-sync cloudflared
```

Choose one file:

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Headless gateway, no published ports. |
| `docker-compose.headless.yml` | Explicitly named equivalent of the default headless file. |
| `docker-compose.with-dashboard.yml` | Companion frontend, default host port 8080. |

For the explicitly named headless variant:

```bash
docker compose -f docker-compose.headless.yml up -d
```

For the dashboard variant, set a strong `BASIC_AUTH_PASSWORD` first:

```bash
docker compose -f docker-compose.with-dashboard.yml up -d
```

The supplied environment template binds this frontend to `127.0.0.1`; visit `http://localhost:8080` on the host. The backend API is not published. Frontend authentication does not protect the API from other containers on its network. Only the dashboard variant consumes the dashboard settings.

Use the selected `-f` argument consistently for `exec`, `logs`, and `down`. Run only one variant for this gateway project. The sync healthcheck waits for a nonempty token before starting the connector; inspect its logs for the actual connection.

## Inspect and start the application

For the default file, non-mutating inspection uses:

```bash
docker compose exec cf-tunnel-sync python app.py --preflight
```

Preflight reads Docker and Cloudflare. It does not prove write permissions or public reachability; starting the gateway itself can modify remote resources.

Start the application stack:

```bash
cd ../app-stack-example
docker compose up -d
curl -I https://app.example.com
```

Replace the domain. The `web` service joins the gateway and backend networks; the database only joins the backend network and has no host port or tunnel label. The demo normally returns HTTP 200 when routing is ready. Exposing a private application requires actual application/Access authentication, not a metadata label.

## Stop the stacks

From `app-stack-example/`:

```bash
docker compose down
cd ../core-tunnel-stack
docker compose down
```

For an alternate gateway file, use its `-f` argument for the final command. Volumes and Cloudflare resources are retained. To let the controller remove an application route, keep the gateway running through the grace period and a later sync before stopping it. See [operations](../../docs/operations.md).
