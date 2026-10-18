# Operations, Teardown & Uninstall Runbook (OPS-03)

This guide documents operational lifecycle transitions, downtime semantics, and safe teardown/uninstallation procedures for `cf-docker-tunnel-sync`.

---

## 1. Operational Lifecycle Transitions

### 1.1 Stopping Origin Application Containers (`docker compose stop`)
When an application container (e.g., `my-app`) is stopped:
- **Tombstoning Phase:** `cf-docker-tunnel-sync` detects that the container is no longer running. Instead of immediately purging its Cloudflare Tunnel Ingress rule and DNS record, it places the hostname into a **tombstone** state for `DNS_CLEANUP_GRACE_PERIOD` seconds (default: 300s / 5 minutes).
- **Ingress Rule State:** During the tombstone window, the ingress rule and DNS record remain active in Cloudflare. Requests from the internet will receive an HTTP 502 Bad Gateway from cloudflared, indicating the origin is temporarily unavailable.
- **Fast Recovery:** If the container restarts before the grace period expires (e.g. during a host reboot, Docker update, or container update), the tombstone is cleared with **zero unnecessary writes** to the Cloudflare API.
- **Grace Period Expiry:** If the container remains stopped past the grace window, `cf-docker-tunnel-sync` cleans up the Ingress rule and deletes the managed DNS CNAME record.

### 1.2 Stopping the Gateway Stack (`docker compose down` on Gateway)
When the gateway stack (`cf-tunnel-sync` + `cloudflared`) is stopped:
- **Tunnel Inactive:** The outbound tunnel connection closes. Internet visitors accessing your domain will receive Cloudflare Error 1033 (Cloudflare Tunnel error: Argo Tunnel is down).
- **DNS Records Preserved:** Existing Cloudflare DNS records remain completely intact in your Cloudflare account. `cf-docker-tunnel-sync` will not delete DNS records when the sync process itself shuts down.
- **Resuming:** Starting the gateway stack (`docker compose up -d`) automatically reconnects the tunnel connector and validates DNS/ingress routing within seconds.

---

## 2. Intentionally Removing a Service Route

To permanently delete an exposed route:
1. **Option A (Container Removal):** Remove the container or remove its `cf.tunnel.*` labels, and allow `DNS_CLEANUP_GRACE_PERIOD` to elapse.
2. **Option B (Immediate Deletion):** Set `DNS_IMMEDIATE_CLEANUP=true` in the gateway environment to skip tombstoning and delete obsolete routes on the next sync cycle.
3. **Option C (Manual Dashboard Deletion):** Use the Cloudflare Zero Trust Dashboard (**Networks → Tunnels → Configure**) or Cloudflare DNS settings.

---

## 3. Safe Uninstallation & Resource Cleanup

If you decide to uninstall `cf-docker-tunnel-sync` from your server:

### Step 1: Teardown Gateway Containers
```bash
cd ~/stacks/gateway
docker compose down -v
```

### Step 2: Remove Shared Bridge Network
```bash
docker network rm cf-tunnel-net
```

### Step 3: Cloudflare Resource Cleanup
Because `cf-docker-tunnel-sync` does not delete all remote resources upon process termination (to protect against accidental service wipes), perform these cleanup steps in your Cloudflare account:

1. **Delete DNS Records:**
   - In Cloudflare Dashboard, go to **Websites → [Your Domain] → DNS → Records**.
   - Filter by comment: `cf-tunnel-sync:<tunnel_name>`.
   - Select and delete the managed CNAME records.
2. **Delete Cloudflare Tunnel:**
   - Go to **Cloudflare Zero Trust → Networks → Tunnels**.
   - Find your tunnel (e.g. `production-gateway`), click the three dots, and select **Delete**.
3. **Revoke API Token:**
   - In **My Profile → API Tokens**, find your scoped sync token and select **Revoke** or **Delete**.
