# Docker Label Reference & Configuration Specification

This document provides the definitive specification of all container labels, environment variables, and auto-discovery algorithms supported by `cf-docker-tunnel-sync`.

---

## 🏷️ Docker Container Labels Reference

Apply these labels to any Docker container to expose it through Cloudflare Tunnels:

| Label | Required? | Default | Valid Values | Description & Detail |
| :--- | :--- | :--- | :--- | :--- |
| **`cf.tunnel.enable`** | **Required**\* | `false` | `true`, `1`, `yes` | Enables management of this container. Containers without this label are completely ignored. *(Legacy alias: `cloudflared.enable`)* |
| **`cf.tunnel.hostname`** | **Required**\* | — | Fully-qualified domain (e.g., `app.example.com`) | Public HTTPS hostname exposed to the internet. Scoped automatically to `DOMAIN_NAME` if only a subdomain is given. *(Legacy alias: `cloudflared.hostname`)* |
| **`cf.tunnel.port`** | Optional | *Auto-detected* | Integer (e.g., `80`, `8080`, `3000`) | Internal container listening port. If omitted, resolved via the port auto-discovery hierarchy. *(Legacy alias: `cloudflared.port`)* |
| **`cf.tunnel.service`** | Optional | *Auto-constructed* | `http://<target>:<port>` or `https://<target>:<port>` | Full origin upstream URL. Overrides hostname/port construction if custom protocols or endpoints are required. *(Legacy alias: `cloudflared.service`)* |
| **`cf.tunnel.path`** | Optional | — | URL path regex (e.g., `/api/*`) | Cloudflare path-matching rule for sub-path routing. *(Legacy alias: `cloudflared.path`)* |
| **`cf.tunnel.originRequest.noTLSVerify`** | Optional | `false` | `true`, `false` | Bypasses TLS certificate verification when connecting to internal origins using self-signed certificates. *(Aliases: `cf.tunnel.no_tls_verify`, `cf.tunnel.notlsverify`)* |
| **`cf.tunnel.originRequest.httpHostHeader`** | Optional | — | String hostname | Overrides the HTTP `Host` header sent to origin service. Useful for Nextcloud or virtual-host reverse proxies. *(Alias: `cf.tunnel.http_host_header`)* |
| **`cf.tunnel.originRequest.originServerName`** | Optional | — | String hostname | Overrides the SNI server name sent during the TLS handshake with origin services. *(Alias: `cf.tunnel.origin_server_name`)* |
| **`cf.tunnel.access.policy`** | Optional | — | String policy tag | Attaches an Access Policy tag in Cloudflare Zero Trust for audit and access tracking. *(Aliases: `cf.tunnel.access_policy`, `cloudflared.access.policy`)* |
| **`cf.tunnel.name`** | Optional | — | String tunnel name | Restricts container to a specific named tunnel in multi-tunnel environments. |

---

## 🔍 Origin Auto-Discovery Algorithms

### 1. Hostname / Target IP Discovery
When routing traffic from `cloudflared` to your target container:
1. **Network Selection:**
   - If the container is connected to `CF_NETWORK_NAME` (`cf-tunnel-net`), that shared network is selected.
   - If `REQUIRE_SHARED_NETWORK=true` and the container does not share a network with `cloudflared`, the container is excluded from synchronization with a diagnostic warning.
   - If multiple networks exist, `cf-tunnel-net` always takes precedence over internal bridge networks.
2. **Target Hostname:**
   - By default, `cloudflared` routes to the container using Docker's internal embedded DNS hostname (the container name or compose service name, e.g. `http://my-app:80`).
   - If the container name is unavailable, its IP on the shared network is utilized.

### 2. Port Discovery Precedence Hierarchy
When `cf.tunnel.port` is not explicitly declared:
1. **Priority 1 (Explicit Label):** `cf.tunnel.port` (or `cloudflared.port`).
2. **Priority 2 (Single `EXPOSE` Directive):** If the image's Dockerfile exposes exactly one port (e.g. `EXPOSE 8080`), that port is automatically selected.
3. **Priority 3 (Fallback Default):** Port `80`. If the container exposes multiple ports (e.g. `80` and `443`) without an explicit label, a diagnostic warning is logged and port `80` is chosen.

---

## ⚙️ Environment Variables Reference

| Variable | Required? | Default | Valid Format | Description & Detail |
| :--- | :--- | :--- | :--- | :--- |
| **`CLOUDFLARE_API_TOKEN`** | **Required** | — | String | Scoped Cloudflare API Token (`Zone:DNS:Edit`, `Account:Tunnel:Edit`, `Zone:Zone:Read`). *(Alias: `CLOUDFLARE_TOKEN`)* |
| **`CLOUDFLARE_TUNNEL_NAME`** | **Required**\* | `cf-docker-tunnel-sync` | String | Name of the Cloudflare Tunnel. Auto-provisioned if it does not exist. *(Alias: `TUNNEL_NAME`)* |
| **`DOMAIN_NAME`** | **Required** | — | Domain name | Primary domain zone managed by Cloudflare (e.g., `example.com`). |
| `CLOUDFLARE_ACCOUNT_ID` | Optional | *auto-detected* | 32-hex string | Cloudflare Account ID. Auto-detected from zone or token if omitted. |
| `CLOUDFLARE_ZONE_ID` | Optional | *auto-detected* | 32-hex string | Cloudflare DNS Zone ID. Auto-detected from `DOMAIN_NAME` if omitted. |
| `CF_NETWORK_NAME` | Optional | `cf-tunnel-net` | String | Docker bridge network connecting `cloudflared` and target services. *(Alias: `CUSTOM_NETWORK`)* |
| `DOCKER_HOST` | Optional | `unix:///var/run/docker.sock` | URI | Docker daemon connection socket or TCP endpoint (e.g. `tcp://socket-proxy:2375`). |
| `SYNC_FALLBACK_INTERVAL` | Optional | `30` | Seconds (int) | Periodic fallback synchronization polling interval. *(Aliases: `SYNC_INTERVAL`, `POLL_INTERVAL`)* |
| `SYNC_DEBOUNCE_SECONDS` | Optional | `2.5` | Seconds (float) | Debounce stabilization delay for rapid Docker events. *(Alias: `SYNC_DEBOUNCE_DELAY`)* |
| `MAX_DELETIONS_PER_SYNC` | Optional | `3` | Integer | Circuit breaker threshold for mass deletions in one sync cycle. *(Alias: `MASS_DELETION_LIMIT`)* |
| `ALLOW_MASS_DELETIONS` | Optional | `false` | Boolean | Circuit breaker override for intentional mass teardown. |
| `DNS_CLEANUP_GRACE_PERIOD`| Optional | `300` | Seconds (int) | Tombstone retention duration before deleting DNS records of stopped containers. |
| `DNS_IMMEDIATE_CLEANUP` | Optional | `false` | Boolean | Bypasses tombstoning and purges DNS records immediately upon container stop. |
| `DRY_RUN` | Optional | `false` | Boolean | Simulates synchronization and logs planned ChangePlan without executing mutations. |
| `PREFLIGHT_ONLY` | Optional | `false` | Boolean | Runs non-mutating validation of credentials, Docker socket, and network reachability, then exits. |
| `LOG_LEVEL` | Optional | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | Logging verbosity. |
| `LOG_FORMAT` | Optional | `text` | `text`, `json` | Log output format. |
