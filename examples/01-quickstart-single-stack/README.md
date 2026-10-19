# Single-stack gateway and HTTP demo

Run this example when you want the synchronizer, `cloudflared`, and a whoami application in one Compose stack. You need a Cloudflare zone, a [scoped token](../../docs/cloudflare-permissions.md), and Docker Compose v2. Choose a dedicated tunnel name and review [current safety limitations](../../docs/architecture-and-safety.md#current-limitations).

## Configure and start

From this directory:

```bash
cp .env.example .env
```

Replace the token and domain in `.env`. The optional account ID is forwarded when configured. `CF_NETWORK_NAME` controls both discovery and the created network. No host ports are published.

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=50 cf-tunnel-sync cloudflared
```

The sync healthcheck waits for a nonempty shared token and the local health endpoint before Compose starts `cloudflared`. This avoids starting a fresh connector without a token; check its logs for the actual edge connection.

## Verify

Replace the domain below with yours:

```bash
curl -I https://whoami.example.com
```

The demo normally returns HTTP 200. The hostname and explicit port labels select the running origin; an enable label is not required. Public whoami demonstrates routing, not user authentication.

To inspect credentials/zone/tunnel and Docker without performing configuration mutations:

```bash
docker compose exec cf-tunnel-sync python app.py --preflight
```

A passing preflight does not prove all write permissions or public reachability. Use [troubleshooting](../../docs/troubleshooting.md) if the public request fails.

## Stop and remove

```bash
docker compose down
```

This retains the token volume and remote Cloudflare resources. For complete removal, follow [operations](../../docs/operations.md#uninstalling). Do not remove a shared network/volume used by another stack.
