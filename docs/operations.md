# Operations

These commands assume the root Compose deployment, a host API port of 8080, and a dashboard user named `admin`. Substitute your port/user. `curl --user admin` prompts for the password. For headless deployments, run an HTTP client from a network that can reach the backend on port 8090.

## Inspect a running gateway

From the gateway's Compose directory:

```bash
docker compose ps
docker compose logs --tail=100 cf-tunnel-sync cloudflared
curl --fail-with-body http://localhost:8080/health
curl --fail-with-body --user admin http://localhost:8080/api/status
```

`/health` is public and reports Docker state. It is not a check of Cloudflare connectivity or successful routing. In `/api/status`, inspect `status`, `last_sync`, `services`, `overview_metrics`, and the diagnostic stages. `last_sync` is a string or null, not an object. See the [API reference](api.md).

To inspect recent events/history:

```bash
curl --fail-with-body --user admin http://localhost:8080/api/events
curl --fail-with-body --user admin http://localhost:8080/api/history
```

## Logs

Text logs explain discovered hostnames, ingress/DNS operations, token updates, and failures. Enable `LOG_FORMAT=json` in the container environment for structured output, then recreate the service. The formatter uses `timestamp`, `level`, `message`, and `logger`; it does not add a `stage` field.

Compose adds a service prefix by default. Suppress that prefix before parsing JSON lines, and expect some non-JSON output from other logging sources:

```bash
docker compose logs --no-log-prefix cf-tunnel-sync | jq -R 'fromjson? | select(.level == "ERROR")'
```

Do not post unreviewed logs or `.env` content in support requests.

## Metrics

By default `/metrics` is unauthenticated. If you enable `METRICS_AUTH_ENABLED`, add `--user admin` to this request:

```bash
curl --fail-with-body http://localhost:8080/metrics
```

Useful registered metrics include:

| Metric | Type | Meaning |
| --- | --- | --- |
| `cf_tunnel_sync_runs_total{status="success"}` | Counter | Recorded successful sync runs; other status labels record degraded/error runs. |
| `cf_tunnel_sync_duration_seconds` | Gauge | Latest recorded duration. |
| `cf_tunnel_sync_last_success_timestamp` | Gauge | Unix timestamp of the latest recorded successful run; zero before one is recorded. |
| `cf_tunnel_sync_failures_total` | Counter | Runs recorded with a non-success status. |
| `cf_tunnel_services_discovered` | Gauge | Latest recorded service count. |
| `cf_tunnel_safety_guard_tripped` | Gauge | Last recorded deletion-guard state. |
| `cf_tunnel_docker_connected` | Gauge | Last reported Docker connection state. |
| `cf_tunnel_api_requests_total` | Counter | Cloudflare requests, labeled by method and status class. |
| `cf_tunnel_cloudflare_errors_total` | Counter | Cloudflare errors by HTTP status code. |
| `cf_tunnel_dns_operations_total` | Counter | DNS operations labeled by operation. |
| `cf_tunnel_ingress_operations_total` | Counter | Ingress operations labeled by operation. |
| `cf_tunnel_webhook_deliveries_total` | Counter | Webhook attempts labeled by success/failure. |

Metrics describe the points where the code records them; early returns can leave previous values. Combine metrics with status/events and a real application check. Older references to `cf_tunnel_sync_reconcile_status`, consecutive-failure gauges, or rate-limit-backoff gauges do not describe the current registry.

## Preflight and manual sync

Run non-mutating inspection using the container's configured environment:

```bash
docker compose exec cf-tunnel-sync python app.py --preflight
```

Preflight reads Docker (including `/version`) and Cloudflare token/zone/tunnel information. A missing tunnel fails inspection even though normal startup can create one. Network inspection warnings do not necessarily make preflight fail. A successful result does not prove DNS edit permission or public reachability.

To request a normal sync:

```bash
curl --fail-with-body --user admin --request POST http://localhost:8080/api/sync
```

This can mutate resources. The request waits for its sync call, or skips when another run holds the lock. Review returned state. `DRY_RUN` is not a fully non-mutating alternative because initialization is outside its guard; see [current limitations](architecture-and-safety.md#current-limitations).

## Stopping and recovering services

When an origin stops, managed ingress/DNS usually remain during the 300-second grace period. Requests can fail while the origin is down. If it returns before cleanup, the tombstone clears. Expiry is processed on a later sync, so actual removal also depends on events and polling.

Stopping the gateway stops its reconciliation and connector. It does not delete remote DNS or the Cloudflare tunnel. Other connectors for the same tunnel, if present, can continue serving it.

To recover on a replacement host, restore your Compose configuration and credentials, recreate the shared network/volume, and start the gateway and applications. The service can obtain the existing tunnel token again. Check routing after recovery; an image starting successfully is not proof that hostnames or networks match.

There is no local database, but the token volume persists and in-memory tombstones/history/caches do not. A process restart can restart a grace period and cause an ingress write.

## Removing a route

Remove the hostname labels or the container and recreate the affected application service. `cf.tunnel.enable=false` does not opt out in the current parser. Allow the grace period and a subsequent sync to run, then inspect Cloudflare records and ingress.

`DNS_IMMEDIATE_CLEANUP=true` changes cleanup for the whole gateway, not just one service. Use it only for an intended teardown after reviewing all affected routes. Manual Cloudflare edits can be recreated or overwritten while a matching desired service remains.

If a deletion guard trips, restore unexpectedly missing services first. Use `ALLOW_MASS_DELETIONS=true` only after checking the full planned removal, then remove the override after the intended cleanup. See [troubleshooting](troubleshooting.md#deletion-guard-tripped).

## Uninstalling

1. Decide which routes/tunnel are dedicated to this gateway, and preserve configuration you still need.
2. Stop the gateway from its Compose directory with `docker compose down`. This retains named volumes.
3. Remove only verified managed Cloudflare CNAMEs and the dedicated tunnel when no other connector/service uses it. Match both target and comment; review the [ownership limitations](architecture-and-safety.md#current-limitations).
4. Revoke credentials no longer used elsewhere.
5. Remove the token volume and shared network only after confirming no other stack uses them. `docker compose down -v` deletes this stack's named volumes, so it is an intentional final cleanup rather than the default first step.

For upgrades and rollback, see [compatibility](COMPATIBILITY.md).
