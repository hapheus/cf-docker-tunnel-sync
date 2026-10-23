# Environment variables

These settings describe the current sync service. Put them in the container's environment, either through a Compose `environment` entry or `env_file`. A value in `.env` is only available for Compose interpolation unless the Compose file passes it into the container.

After changing container environment values, recreate the service:

```bash
docker compose up -d cf-tunnel-sync
```

A container restart alone does not load changed environment values. The root Compose file forwards a subset of the settings below; add an `environment` entry for other settings you use.

## Cloudflare

| Variable | Default | Behavior |
| --- | --- | --- |
| `CLOUDFLARE_API_TOKEN` | Required | Scoped token for the normal sync loop. |
| `DOMAIN_NAME` | Required | Cloudflare zone name, such as `example.com`. Discovered hostnames must be that domain or a subdomain. |
| `CLOUDFLARE_TUNNEL_NAME` | `cf-docker-tunnel-sync` | Looks up an active tunnel by name and creates one if none is found. |
| `CLOUDFLARE_ACCOUNT_ID` | Discovered | Uses the account returned with the zone. If absent there, the implementation falls back to the first account returned by the token. Set this explicitly when account selection could be ambiguous. |

The sync loop resolves the zone from `DOMAIN_NAME` and the tunnel from its name on each run. Use a dedicated tunnel for this synchronizer; see [ownership and limitations](architecture-and-safety.md).

## Docker and networking

| Variable | Default | Behavior |
| --- | --- | --- |
| `DOCKER_HOST` | Empty | `tcp://` or `http://` selects a plain HTTP Docker endpoint. Otherwise the Unix socket path below is used. This client does not implement Docker TLS environment settings. |
| `DOCKER_SOCKET` | `/var/run/docker.sock` | Unix socket path; falls back to `DOCKER_SOCKET_PATH`. |
| `DOCKER_TIMEOUT` | `10` seconds | Timeout for Docker requests. |
| `DOCKER_RETRIES` | `3` | Total request attempts. |
| `CF_NETWORK_NAME` | `cf-tunnel-net` | Expected connector network used during discovery and network diagnostics. |
| `REQUIRE_SHARED_NETWORK` | `false` | Excludes origins that fail the network plausibility check when enabled. |
| `STRICT_NETWORK_CHECK` | `false` | Also enables that exclusion; either setting is sufficient. |
| `CLOUDFLARED_CONTAINER_NAME` | Auto-selected | Explicit connector target. Otherwise the service tries to find a matching connector; see [networking](networking-guide.md). |

The synchronizer reads container inventory and Docker events. It also attempts a connector restart after updating its token. A [GET-only socket proxy](security.md#docker-socket-access) prevents that restart.

## Scheduling

| Variable | Default | Behavior |
| --- | --- | --- |
| `SYNC_FALLBACK_INTERVAL` | `900` seconds | Periodic sync; precedence is this variable, `SYNC_INTERVAL`, then `POLL_INTERVAL`. |
| `SYNC_DEBOUNCE_SECONDS` | `2.5` seconds | Coalesces bursts of Docker events; falls back to `SYNC_DEBOUNCE_DELAY`. |
| `SYNC_DEBOUNCE_MAX_DELAY` | `10` seconds | Maximum postponement during an event burst. |
| `FILTER_UNLABELED_EVENTS` | `true` | Ignores lifecycle events from containers without Cloudflare tunnel labels or connector roles. Set to `false` to trigger sync on all container events. |

An initial sync starts when the application starts. Configure positive intervals and valid numeric values; invalid scheduling values are not uniformly validated.

## Ownership and deletion

| Variable | Default | Behavior |
| --- | --- | --- |
| `OWNERSHIP_POLICY` | `adopt_and_manage` | `adopt_and_manage` tags matching untagged CNAMEs for active services; `strict_tagged_only` protects them from adoption; `legacy_unrestricted` relaxes cleanup rules for old deployments. |
| `DNS_CLEANUP_GRACE_PERIOD` | `300` seconds | Grace period for missing managed origins and their DNS records. |
| `DNS_IMMEDIATE_CLEANUP` | `false` | Bypasses the normal grace period. |
| `MAX_DELETIONS_PER_SYNC` | `3` | Execution limit; falls back to `MAX_DELETIONS_PER_RUN`. Ingress and DNS deletion counts are combined as the larger count, not their sum. |
| `MAX_DELETIONS_PER_RUN` | Unset | Legacy execution limit when `MAX_DELETIONS_PER_SYNC` is unset. |
| `MAX_DELETION_RATIO` | Unset | Optional deletion fraction, such as `0.5`; evaluated against discovered services plus planned deletions. |
| `ALLOW_MASS_DELETIONS` | `false` | Overrides execution deletion limits. |

Use `strict_tagged_only` when you do not want matching existing CNAMEs adopted. This is not an unconditional preservation guarantee: [known ownership and ingress limitations](architecture-and-safety.md#current-limitations) still apply.

## Dashboard, API, and logs

The Python service listens on `0.0.0.0:8090`. The root Compose file publishes it on host port `8080` by default.

| Variable | Default in the Python service | Behavior |
| --- | --- | --- |
| `DASHBOARD_ENABLED` | `true` | Serves `/` and `/dashboard`; also reads `EMBEDDED_DASHBOARD_ENABLED` if unset. Disabling the UI leaves API endpoints active. |
| `DASHBOARD_AUTH_ENABLED` | Automatic | Explicit `false` disables dashboard/API auth. Explicit `true` requires nonempty username/password. If unset, credentials enable auth when present. The root Compose file explicitly defaults this to `true`. |
| `DASHBOARD_USERNAME` | Empty | Falls back to `BASIC_AUTH_USERNAME` only when unset. |
| `DASHBOARD_PASSWORD` | Empty | Falls back to `BASIC_AUTH_PASSWORD` only when unset. |
| `METRICS_AUTH_ENABLED` | `false` | Separately protects `/metrics` using the same credentials. |
| `LOG_LEVEL` | `INFO` | Logging verbosity. |
| `LOG_FORMAT` | `text` | `text` or `json`. |

`DASHBOARD_PORT` and `DASHBOARD_BIND_ADDRESS` affect the **host port mapping in the root Compose file**. They do not change the Python listener. To keep the dashboard local to the host, use `DASHBOARD_BIND_ADDRESS=127.0.0.1` with that Compose file.

The optional companion dashboard also accepts `SYNC_BACKEND_HOST` and `SYNC_BACKEND_PORT` for its proxy target. Its authentication is configured separately; consult its [README](../cf-tunnel-dashboard/DOCKERHUB.md).

## Notifications and Cloudflare retries

| Variable | Default | Behavior |
| --- | --- | --- |
| `NOTIFICATION_WEBHOOK_URL` | Empty | Enables alert delivery when configured; treat the URL as a secret. |
| `NOTIFICATION_WEBHOOK_TYPE` | `auto` | Provider selection is derived from the URL by default. The current default dispatcher supplies `auto` to its constructor, so use the URL-derived behavior rather than relying on this environment override. |
| `NOTIFICATION_COOLDOWN_SECONDS` | `300` seconds | Cooldown for duplicate alerts. |
| `CLOUDFLARE_RETRY_BASE_DELAY` | `0.5` seconds | Base delay for retryable Cloudflare responses/network failures. |
| `CLOUDFLARE_MAX_RETRIES` | `3` | Configures the client default, but the normal sync helper supplies its own default of three attempts. Do not rely on this variable to change normal sync attempts. |

## Preflight and dry-run

`PREFLIGHT_ONLY=true` or `python app.py --preflight` performs inspection and exits. It can read Docker and Cloudflare; it does not provision resources. A successful exit does not prove public reachability or every token permission.

`DRY_RUN=true` or `python app.py --dry-run` prevents tunnel creation, token-file writes, connector restarts, and ingress/DNS writes. When the tunnel does not exist, the cycle reports that provisioning is required and does not invent a tunnel ID or dependent DNS target. Otherwise it reads remote state and computes a plan. Preflight provides configuration and connectivity diagnostics without provisioning. See [current limitations](architecture-and-safety.md#current-limitations).

## Settings with limited or no effect in normal sync

Some names are recognized by configuration validation or used in other entry points but are not runtime switches for normal synchronization:

- `CLOUDFLARE_TOKEN`: read by preflight's token helper; normal synchronization requires `CLOUDFLARE_API_TOKEN`.
- `CLOUDFLARE_TUNNEL_ID`: validated at startup and inspected by preflight; normal sync still selects by tunnel name.
- `CLOUDFLARE_ZONE_ID`: used by the fallback preview; normal sync resolves the zone from `DOMAIN_NAME`.
- `TUNNEL_NAME`, `CUSTOM_NETWORK`, `HOST_IP`, `AUTO_CREATE_TUNNEL`, `CLOUDFLARE_DNS_PROXIED`, `PROXIED`, `INITIAL_DELAY`, `FALLBACK_INTERVAL`, `DEBOUNCE_SECONDS`, `DEBOUNCE_WAIT_SECONDS`, `ENABLE_DEBOUNCING`, `MAX_DELETIONS_THRESHOLD`, `MASS_DELETION_LIMIT`, `PORT`, `PROMETHEUS_PORT`, `PROMETHEUS_METRICS_ENABLED`, `STRICT_HEALTH_STATUS`, and `ENABLE_CHANGE_PLAN` do not control the corresponding normal-sync behavior advertised in older documentation.

For example, `AUTO_CREATE_TUNNEL=false` does not prevent tunnel creation, and `STRICT_HEALTH_STATUS=true` does not make `/health` return HTTP 503. Use the documented active settings above.
