# HTTP API

The backend serves its API on port `8090`. The root Compose file publishes it on host port `8080` by default. The embedded dashboard and optional companion dashboard consume these endpoints; neither is required for headless operation.

## Authentication

Dashboard and `/api/*` routes share HTTP Basic authentication. The rules are:

- `DASHBOARD_AUTH_ENABLED=false` explicitly disables it.
- `DASHBOARD_AUTH_ENABLED=true` requires nonempty username/password and rejects protected requests with HTTP 401 when either is missing.
- If the setting is absent, configuring either credential enables the authentication checks. With both absent, access is unauthenticated.

Use `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`, or the fallback `BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD`. The root Compose file defaults authentication to enabled. The companion frontend has separate authentication settings. See [configuration](configuration.md).

For a root-Compose deployment, this command prompts for the configured user's password without putting it in the command:

```bash
curl --fail-with-body --user admin http://localhost:8080/api/status
```

Replace `admin` if needed. Basic authentication requires a trusted connection or TLS for exposed deployments. Probes are public. `/metrics` has a separate auth switch.

## Endpoint summary

| Method and path | Authentication | Response |
| --- | --- | --- |
| `GET /health`, `GET /healthz` | Public | HTTP 200; `healthy` or `degraded` based on Docker state. |
| `GET /ready` | Public | HTTP 200 when Docker is marked connected, otherwise 503. |
| `GET /metrics` | Separate metrics setting | Prometheus text, HTTP 200. |
| `GET /api/status` | Dashboard setting | Public sync state, HTTP 200. |
| `GET /api/events` | Dashboard setting | Filtered event timeline, HTTP 200. |
| `GET /api/history` | Dashboard setting | Recent cycle history, HTTP 200. |
| `GET /api/notifications/status` | Dashboard setting | Alert-delivery status, HTTP 200. |
| `GET /api/change-plan` | Dashboard setting | Latest plan in the action/summary representation, or a locally computed fallback. |
| `GET /api/sync/preview`, `GET /api/v1/sync/preview` | Dashboard setting | Cached or locally computed plan in a wrapper. |
| `POST /api/sync` | Dashboard setting | Waits for the sync call and returns state, HTTP 200; inspect state for success/failure. |
| `GET /`, `GET /dashboard` | Dashboard setting | HTML when enabled, otherwise HTTP 404 JSON. |

Normal FastAPI parameter-validation errors return HTTP 422. Authentication failures return HTTP 401. Runtime/request failures can produce server errors; a 200 response from a status endpoint is not a health guarantee.

## Health and readiness

Example `/health` response:

```json
{"status":"healthy","docker_connected":true,"sync_status":"Active / Synced"}
```

When disconnected, `/health` still returns HTTP 200 with `status: "degraded"`. `/ready` returns HTTP 503 and `status: "not ready"`. Its successful status is `ready`.

These probes reflect the Docker-connected flag, which is initially true. They do not validate token-file availability, successful initial synchronization, the connector's edge connection, or origin reachability. `STRICT_HEALTH_STATUS` does not change the current health handler.

## Status

`GET /api/status` returns the current public state. Important fields include:

| Field | Typical type | Meaning |
| --- | --- | --- |
| `status` | String | For example `Initializing`, `Active / Synced`, `Degraded`, or `SAFETY_GUARD_TRIPPED`. |
| `last_sync` | String or null | Recorded sync time, formatted as `YYYY-MM-DD HH:MM:SS`; not a nested result object or guaranteed UTC timestamp. |
| `domain_name`, `tunnel_name` | Strings | Configured scope. |
| `tunnel_id` | String or null | Resolved tunnel. |
| `docker_connected` | Boolean | Last known Docker connection state. |
| `services`, `discovered_services` | Lists in the normal sync pipeline | Service dictionaries with hostname, service URL, diagnostic stages, status, and Access metadata. |
| `all_containers`, `dns_records` | Lists | Discovery summaries and intended DNS display entries. |
| `logs`, `events`, `sync_history` | Lists | Bounded in-memory diagnostics. |
| `overview_metrics` | Object | Service counts, latest duration, connection and health summaries. |
| `safety_guard_tripped`, `safety_details` | Boolean, object or null | Recorded deletion-guard information. |
| `alert_status` | Object | Notification configuration/delivery summary. |
| `last_change_plan` | Object or null | Internal plan model serialized for status; differs from the action representation below. |

Fields depend on how far initialization has progressed. The serializer passes through public state rather than enforcing a single response model; do not infer extra stable fields from examples in older documentation. Existing contract tests also allow `services` to be an object for compatibility, although normal synchronization publishes a list.

Keys starting with `_` are omitted. Recognized sensitive keys and text are redacted. The status display is not an independent remote audit: for example, DNS display entries are assembled from intended services and tombstones even after partial execution failures.

## Events, history, and notifications

`GET /api/events` accepts:

- `limit`: integer, default 100, clamped to 1–100.
- `severity`: case-insensitive exact severity filter.
- `service`: case-insensitive substring filter.
- `q`: case-insensitive substring search across message, event type, and service.

The response contains `events` and `total`; total is the filtered count before the limit. Events include `id`, Unix `timestamp`, `iso_time`, `severity`, `event_type`, `service`, and `message`.

`GET /api/history` returns `history` and `total`. Its `limit` defaults to 20 and is clamped to 1–20. Each entry includes `timestamp`, `iso_time`, `duration_ms`, `status`, `services_count`, and a plan `summary` when available. History and events reset on process restart.

`GET /api/notifications/status` returns `configured`, `provider`, `last_delivery_success`, `last_delivery_time`, `last_delivery_status`, `consecutive_failures`, `cooldown_active`, and `cooldown_seconds`. Delivery fields may be null before an attempt. It does not return the webhook URL.

## Change plans and previews

`GET /api/change-plan` uses the latest plan when available. Its action representation has this shape; this example is an empty dry-run plan:

```json
{
  "plan_id": "plan-example",
  "dry_run": true,
  "timestamp": 1792311968.0,
  "actions": [],
  "summary": {
    "additions": 0,
    "updates": 0,
    "deletions": 0,
    "unmanaged_skipped": 0
  }
}
```

An action has `action`, `resource`, `target`, and `reason`. Ingress targets include hostname, service, path, and origin-request options. DNS targets include hostname, record ID/type, current/target content, proxy status, and TTL. Summary additions/updates/deletions count ingress and DNS actions separately, unlike the execution guard's deletion count.

If no plan exists, this endpoint discovers Docker containers and computes against cached ingress and an empty DNS inventory. It does not fetch fresh remote state; IDs can be placeholders.

Both preview paths return `status` (`cached` or `computed`) and `plan`. The plan is the serialized internal model containing `ingress_changes`, `dns_changes`, `final_ingress_rules`, and its detailed summary, rather than the action representation above. Cached mode returns the last plan, which can be from a live run. Fallback mode reads local Docker state but assumes empty remote ingress/DNS. Treat it as a local estimate, not an accurate remote diff.

These GET endpoints do not execute their computed plans. They may perform Docker reads and update the in-memory fallback-plan cache. Starting the daemon in `DRY_RUN` mode also prevents external writes, including initialization; see [safety limitations](architecture-and-safety.md#current-limitations).

## Manual synchronization

```bash
curl --fail-with-body --user admin --request POST http://localhost:8080/api/sync
```

The handler awaits the sync function in a worker thread. It returns `message: "Sync triggered"` and sanitized `state` after that call returns. If a cycle is already running, the sync function skips this request. Inspect the returned status/events rather than treating HTTP 200 as proof of a successful new cycle.

## Metrics and dashboard

`GET /metrics` returns Prometheus text (`text/plain; version=0.0.4`). Authentication is enabled only by `METRICS_AUTH_ENABLED=true`. Metric names and examples are listed in [operations](operations.md#metrics).

The embedded dashboard sets Content-Security-Policy, X-Content-Type-Options, and X-Frame-Options headers. With `DASHBOARD_ENABLED=false`, the HTML routes return HTTP 404 with `status: "disabled"`; APIs and probes remain active.
