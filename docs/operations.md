# Operations, Observability & Runbook

This guide documents operational lifecycle transitions, headless CLI diagnostics, downtime semantics, and safe teardown/uninstallation procedures for `cf-docker-tunnel-sync`.

---

## 1. Headless CLI Observability (No Dashboard Required)

`cf-tunnel-sync` is fully observable in headless environments via standard CLI tools (`curl`, `jq`, `docker logs`), without requiring any web UI or browser access.

### 1.1 Instant Health & Last-Sync Check
Query the internal status endpoint to immediately inspect synchronization state:

```bash
curl -s http://localhost:8090/health
# Expected: {"status":"healthy"}
```

For detailed operational diagnostics:
```bash
curl -s http://localhost:8090/api/status | jq .
```

#### Interpreting Status Output:
```json
{
  "status": "healthy",
  "version": "1.19.0",
  "last_sync": {
    "status": "SUCCESS",
    "timestamp": 1729245600.0,
    "duration_seconds": 0.42,
    "failing_stage": null,
    "routes_managed": 4,
    "action_counts": {
      "added": 1,
      "updated": 0,
      "deleted": 0
    }
  },
  "circuit_breaker": {
    "tripped": false,
    "threshold": 3
  },
  "rate_limiting": {
    "active": false,
    "consecutive_failures": 0
  }
}
```

* **Identify Last Good Sync:** Read `last_sync.timestamp` and `last_sync.status`.
* **Diagnose Failures:** If `last_sync.status` is `"FAILED"`, `last_sync.failing_stage` pinpoints the exact failure component:
  - `docker_socket`: Unable to connect to `/var/run/docker.sock`.
  - `cloudflare_api_auth`: Invalid token or missing permissions.
  - `cloudflare_rate_limit`: Cloudflare API HTTP 429 response, backoff active.
  - `circuit_breaker_tripped`: Planned deletions exceed `MAX_DELETIONS_PER_SYNC`.
  - `dns_zone_resolution`: Domain zone could not be resolved.

### 1.2 Inspecting Logs via Docker CLI
Filter and stream logs directly from the daemon:

```bash
# View all recent reconciliation events
docker compose logs --tail=100 -f cf-tunnel-sync | grep -E "ChangePlan|RECONCILE|ERROR|WARN"

# Example successful log line:
# [INFO] ChangePlan computed: 1 to add, 0 to update, 0 to delete. Reconcile completed in 0.38s.

# Example circuit-breaker safety log line:
# [WARNING] Blast-radius protection tripped: 5 planned deletions exceeds threshold 3. Sync aborted. Set ALLOW_MASS_DELETIONS=true to override.
```

If structured JSON logging is enabled (`LOG_FORMAT=json`), parse with `jq`:
```bash
docker compose logs -f cf-tunnel-sync | jq -r 'select(.level=="ERROR") | "\(.timestamp) [\(.stage)] \(.message)"'
```

### 1.3 Command-Line Prometheus Metrics Scraping
Operators using Prometheus or command-line scripts can inspect raw Prometheus metrics:

```bash
curl -s http://localhost:8090/metrics | grep cf_tunnel_sync_
```

Key gauges for alerting:
- `cf_tunnel_sync_reconcile_status`: `1` for success, `0` for failure.
- `cf_tunnel_sync_last_reconcile_timestamp_seconds`: Unix timestamp of last completed sync.
- `cf_tunnel_sync_consecutive_failures`: Counter of sequential failures (triggers alerts if > 3).
- `cf_tunnel_sync_rate_limit_backoff_active`: `1` if backing off due to Cloudflare HTTP 429.

---

## 2. Operational Lifecycle Transitions

### 2.1 Stopping Origin Application Containers (`docker compose stop`)
When an application container (e.g., `my-app`) is stopped:
- **Tombstoning Phase:** `cf-docker-tunnel-sync` detects that the container is no longer running. Instead of immediately purging its Cloudflare Tunnel Ingress rule and DNS record, it places the hostname into a **tombstone** state for `DNS_CLEANUP_GRACE_PERIOD` seconds (default: 300s / 5 minutes).
- **Ingress Rule State:** During the tombstone window, the ingress rule and DNS record remain active in Cloudflare. Requests from the internet will receive an HTTP 502 Bad Gateway from cloudflared, indicating the origin is temporarily unavailable.
- **Fast Recovery:** If the container restarts before the grace period expires (e.g. during a host reboot, Docker update, or container update), the tombstone is cleared with **zero unnecessary writes** to the Cloudflare API.
- **Grace Period Expiry:** If the container remains stopped past the grace window, `cf-docker-tunnel-sync` cleans up the Ingress rule and deletes the managed DNS CNAME record.

### 2.2 Stopping the Gateway Stack (`docker compose down` on Gateway)
When the gateway stack (`cf-tunnel-sync` + `cloudflared`) is stopped:
- **Tunnel Inactive:** The outbound tunnel connection closes. Internet visitors accessing your domain will receive Cloudflare Error 1033 (Cloudflare Tunnel error: Argo Tunnel is down).
- **DNS Records Preserved:** Existing Cloudflare DNS records remain completely intact in your Cloudflare account. `cf-docker-tunnel-sync` will not delete DNS records when the sync process itself shuts down.
- **Resuming:** Starting the gateway stack (`docker compose up -d`) automatically reconnects the tunnel connector and validates DNS/ingress routing within seconds.

---

## 3. Backup, State Recovery & Disaster Recovery

### Zero-Local-State Architecture
`cf-docker-tunnel-sync` is **100% stateless**. It stores no persistent SQLite or JSON database files on disk. Its source of truth is:
1. The currently running Docker containers (queried live via the Docker socket).
2. The remote Cloudflare Tunnel configuration and DNS records (queried live via Cloudflare API).

### Disaster Recovery Runbook
If the host server experiences catastrophic hardware failure or is replaced:
1. Re-deploy your `docker-compose.yml` and `.env` files on the replacement host.
2. Ensure your domain and API token are defined.
3. Start the gateway and application stacks:
   ```bash
   docker compose up -d
   ```
4. `cf-docker-tunnel-sync` starts, queries the running containers, interrogates the existing Cloudflare Tunnel, reconciles any discrepancies, and restores full connectivity within seconds without manual intervention.

---

## 4. Intentionally Removing a Service Route

To permanently delete an exposed route:
1. **Option A (Container Removal):** Remove the container or remove its `cf.tunnel.*` labels, and allow `DNS_CLEANUP_GRACE_PERIOD` to elapse.
2. **Option B (Immediate Deletion):** Set `DNS_IMMEDIATE_CLEANUP=true` in the gateway environment to skip tombstoning and delete obsolete routes on the next sync cycle.
3. **Option C (Manual Dashboard Deletion):** Use the Cloudflare Zero Trust Dashboard (**Networks → Tunnels → Configure**) or Cloudflare DNS settings.

---

## 5. Safe Uninstallation & Resource Cleanup

If you decide to uninstall `cf-docker-tunnel-sync` from your server:

### Step 1: Teardown Gateway Containers
```bash
cd ~/cf-tunnel
docker compose down -v
```

### Step 2: Remove Shared Bridge Network
```bash
docker network rm cf-tunnel-net
```

### Step 3: Cloudflare Resource Cleanup
Because `cf-docker-tunnel-sync` does not delete remote resources upon process termination (to protect against accidental service wipes), perform these cleanup steps in your Cloudflare account:

1. **Delete DNS Records:**
   - In Cloudflare Dashboard, go to **Websites → [Your Domain] → DNS → Records**.
   - Filter by comment: `cf-tunnel-sync:<tunnel_name>`.
   - Select and delete the managed CNAME records.
2. **Delete Cloudflare Tunnel:**
   - Go to **Cloudflare Zero Trust → Networks → Tunnels**.
   - Find your tunnel (e.g. `cf-docker-tunnel-sync`), click the three dots, and select **Delete**.
3. **Revoke API Token:**
   - In **My Profile → API Tokens**, find your scoped sync token and select **Revoke** or **Delete**.
