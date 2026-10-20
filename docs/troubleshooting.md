# Troubleshooting

Run commands from the gateway's Compose directory unless a step says otherwise. API examples assume the root Compose host port 8080 and user `admin`; replace them for your deployment. `--user admin` prompts for the password.

Start with:

```bash
docker compose ps
docker compose logs --tail=100 cf-tunnel-sync cloudflared
curl --fail-with-body --user admin http://localhost:8080/api/status
```

For non-mutating inspection of the configured Docker and Cloudflare resources:

```bash
docker compose exec cf-tunnel-sync python app.py --preflight
```

Preflight can fail for a missing tunnel before normal startup has created it. Passing preflight does not prove DNS write permission or application reachability. Dry-run prevents external writes and reports a missing tunnel as a provisioning prerequisite; see [architecture and safety](architecture-and-safety.md).

## Service is not discovered

Check the application's labels, running state, domain, and tunnel selection:

```bash
docker inspect <application-container> --format '{{json .Config.Labels}}'
```

Use a single fully qualified `cf.tunnel.hostname` under `DOMAIN_NAME`. Verify that `cf.tunnel.name`, if set, matches this gateway. Set `cf.tunnel.port` explicitly. A false enable label does not disable current discovery. See [labels](labels.md).

Apply changed labels from the application stack's directory with `docker compose up -d <service>`. A plain restart does not apply Compose changes.

## Hostname does not resolve

Query public address records from a client with `dig` installed:

```bash
dig @1.1.1.1 app.example.com A
dig @1.1.1.1 app.example.com AAAA
```

`1.1.1.1` is a recursive resolver, not your domain's authoritative nameserver. An empty CNAME answer alone is not evidence of a missing proxied record: [proxied records return Cloudflare addresses](https://developers.cloudflare.com/dns/proxy-status/).

Check the stored record in Cloudflare DNS: hostname, CNAME target `<tunnel-id>.cfargotunnel.com`, proxy state, and ownership comment. Then check sync logs for DNS creation/collision errors. Do not delete an existing record until you know what uses it.

If the record is correct but resolvers disagree, inspect delegation and caches. Avoid assuming every propagation problem resolves within five minutes. A request outside the configured `DOMAIN_NAME` scope is not fixed by giving the token access to another zone.

## Tunnel-origin 502

A tunnel-origin 502 usually means the connector is connected but cannot reach the origin; 1033 is a different failure. See [Cloudflare's tunnel troubleshooting](https://developers.cloudflare.com/tunnel/troubleshooting/).

Check:

1. The origin URL in status: correct `http`/`https`, name, and internal port.
2. Connector and application membership in `cf-tunnel-net`:

   ```bash
   docker network inspect cf-tunnel-net
   ```

3. Application logs and its actual listening interface. Docker `EXPOSE`/`docker port` metadata does not prove a process is listening. It usually must bind beyond container loopback.
4. For HTTPS origins, certificate trust and server name. See [TLS labels](labels.md#https-origins).

The official connector image may not contain a shell, `curl`, or `nc`. If needed, run a disposable client on the same network; this example pulls an image and contacts the application:

```bash
docker run --rm --network cf-tunnel-net curlimages/curl:latest --head --max-time 10 http://<application-container>:8080
```

Use an approved/pinned diagnostic image for your environment. A successful response establishes that this client can reach the application on that network; it does not reproduce all connector-specific TLS settings. Persist network changes in Compose rather than relying on a temporary `docker network connect`.

## Error 1033 or connector disconnected

Inspect `cloudflared` logs first. Verify its command uses `--token-file /etc/cloudflared/token` and both gateway services mount the same token volume. Do not print the token during diagnosis.

Check for token-write or connector-restart notices in sync logs. A read-only socket proxy blocks restart POSTs. After confirming the token is initialized, explicitly restart the connector if needed:

```bash
docker compose restart cloudflared
```

Also check host/network access to Cloudflare. [Error 1033](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1033/) means Cloudflare cannot find a healthy connector for the tunnel; changing the application's port alone will not reconnect it.

## Token or permission error

Run preflight and inspect its token/zone/tunnel diagnostics. A valid token can still lack access to a resource or lack DNS edit permission. Compare its scope with the [permission guide](cloudflare-permissions.md), and confirm `CLOUDFLARE_API_TOKEN` is actually passed into the container.

Update credentials through your normal secret configuration and recreate the sync service. Do not paste a real token into shared command output or support messages.

## Dashboard returns 401

The root Compose deployment enables authentication. Both username and password must be nonempty. Verify their presence privately; do not dump `.env` or resolved Compose configuration into a support report.

After changing the environment file or Compose settings, recreate the service:

```bash
docker compose up -d cf-tunnel-sync
```

Use `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` for the embedded dashboard. The companion Nginx dashboard uses its own `BASIC_AUTH_*` settings. See [authentication](api.md#authentication). A restart alone does not reload changed container environment values.

## Deletion guard tripped

Inspect both state and the latest plan:

```bash
curl --fail-with-body --user admin http://localhost:8080/api/status
curl --fail-with-body --user admin http://localhost:8080/api/change-plan
```

Restore unexpectedly missing applications before overriding protection. For an intended mass removal, pass `ALLOW_MASS_DELETIONS=true` into the sync container's environment, recreate it, verify the resulting cleanup, then remove the override. The root Compose file does not forward every setting automatically; setting an unused `.env` key alone has no effect.

An immediate-cleanup override affects the entire gateway. See [ownership/deletion configuration](configuration.md#ownership-and-deletion).

## API says synced but the application fails

A successful configuration cycle is not an end-to-end application health probe. Network diagnostics are plausibility checks; status DNS entries can reflect intent after partial errors. Check per-service stages, events, actual Cloudflare configuration, connector logs, and a public request.

An Access metadata label is not authentication. If the route should be private, verify its real application/Access policy. Existing manual ingress rules also have [preservation limitations](architecture-and-safety.md#current-limitations).
