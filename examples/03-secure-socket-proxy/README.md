# Docker socket proxy

This example filters Docker API access with [Tecnativa's socket proxy](https://github.com/Tecnativa/docker-socket-proxy). The sync container has no direct socket mount. You still need Docker Compose v2, a Cloudflare zone, and a [scoped token](../../docs/cloudflare-permissions.md).

An unfiltered `/var/run/docker.sock:ro` mount permits Docker API mutation requests: the mount flag does not restrict HTTP methods. Here the proxy explicitly permits container/event reads, `/version`, and ping; `POST=0` restricts requests to GET/HEAD. Its TCP port is only accessible on the private proxy network, not published on the host.

## Configure and start

From this directory:

```bash
cp .env.example .env
```

Replace token/domain and select a dedicated tunnel. The optional account ID is forwarded. The network setting is applied to both discovery and the actual gateway network.

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=50 cf-tunnel-sync cloudflared docker-socket-proxy
```

The sync healthcheck requires a nonempty shared token before the connector starts. The proxy intentionally blocks automatic connector-restart POSTs; an initial restart notice can appear while the token is being initialized.

## Verify

Replace the domain:

```bash
curl -I https://secured.example.com
docker compose exec cf-tunnel-sync python app.py --preflight
```

The public demo normally returns HTTP 200. `secured` is an example hostname, not a claim of application authentication. Preflight's `/version` request is explicitly permitted by this proxy configuration, but passing it still does not prove public reachability or write permissions.

## After a token change

The synchronizer writes the shared token but cannot restart the connector through this proxy. After verifying initialization in logs, restart it manually when necessary:

```bash
docker compose restart cloudflared
```

Do not enable broad mutation access solely to hide this notice. A proxy also exposes the metadata covered by its allowed API sections; it is not an authorization boundary between application users.

## Stop

```bash
docker compose down
```

This retains remote Cloudflare resources and named volumes. See [security](../../docs/security.md) and [operations](../../docs/operations.md) for credential handling and full cleanup.
