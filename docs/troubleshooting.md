# Task-Based Troubleshooting Guide

This guide provides deterministic **Symptom → Check → Fix** workflows for operational issues with `cf-docker-tunnel-sync`.

---

## 🔍 Diagnostic Toolkit Quick-Reference

Before diving into specific symptoms, run the non-mutating preflight validation mode:

```bash
docker exec cf-tunnel-sync python app.py --preflight
```
*Expected Output:*
```text
🔍 Starting Non-Mutating Preflight Validation (R01)
  [PASS] Docker Socket Check
  [PASS] Cloudflare Token Check
  [PASS] Domain Zone Check
  [PASS] Tunnel Registration Check
  [PASS] Network Topology Check
  [PASS] Ingress Route Syntax Check
==================================================
✅ Preflight validation PASSED: 0 errors, 0 warnings
==================================================
```

---

## 🛠️ Symptom Workflows

### 1. DNS Not Resolving (`NXDOMAIN` or Name Not Found)

- **Symptom:** Browsing `https://app.example.com` returns `DNS_PROBE_FINISHED_NXDOMAIN`.
- **Check:**
  ```bash
  # Check if CNAME record was published to Cloudflare DNS
  dig CNAME app.example.com @1.1.1.1 +short
  ```
- **Diagnostic Inspection:**
  Check sync engine logs for DNS mutations:
  ```bash
  docker logs cf-tunnel-sync --tail 50 | grep "DNS"
  ```
- **Fix:**
  1. Ensure container label `cf.tunnel.hostname` is formatted correctly with your managed domain zone (e.g., `cf.tunnel.hostname=app.example.com`).
  2. If the domain zone does not match `DOMAIN_NAME`, ensure your API token has `Zone:Read` permission across the target zone.
  3. Trigger an immediate reconciliation cycle:
     ```bash
     curl -s -X POST http://localhost:8080/api/sync
     ```

---

### 2. Cloudflare Error 502 Bad Gateway or Error 1033

- **Symptom:** Cloudflare branded error page displays "502 Bad Gateway" or "Error 1033: Argo Tunnel error".
- **Check:**
  Verify whether `cloudflared` can reach the container port via HTTP inside Docker:
  ```bash
  docker exec cloudflared nc -zv <container-name> <port>
  # Or with curl
  docker exec cloudflared curl -I http://<container-name>:<port>
  ```
- **Expected Outcome:** `HTTP/1.1 200 OK` or `Connection open`.
- **Fix:**
  1. **Disjoint Networks:** Both `cloudflared` and your target container must be attached to the shared bridge network (`cf-tunnel-net`):
     ```bash
     docker network inspect cf-tunnel-net | grep -E "(cloudflared|<container-name>)"
     ```
     If missing, attach your container:
     ```bash
     docker network connect cf-tunnel-net <container-name>
     ```
  2. **Wrong Port:** If your application listens on port `3000` or `8080`, declare `cf.tunnel.port=3000`. By default, unlabelled multi-port images fall back to port `80`.

---

### 3. Connection Refused / Wrong Port

- **Symptom:** Sync log outputs `Connection refused` or container logs show no incoming requests.
- **Check:**
  Inspect listening ports inside your container:
  ```bash
  docker port <container-name>
  # Check Docker inspection for internal exposed ports
  docker inspect <container-name> --format '{{json .NetworkSettings.Ports}}'
  ```
- **Fix:**
  Set the explicit two-label configuration:
  ```yaml
  labels:
    - "cf.tunnel.hostname=app.example.com"
    - "cf.tunnel.port=8080" # Match the port your app listens on
  ```

---

### 4. Disjoint Docker Networks (502 Prevention)

- **Symptom:** Preflight or dashboard displays:
  `⚠️ [NET] Container networks do not overlap with connector networks. Requests will fail with 502 Bad Gateway!`
- **Check:**
  ```bash
  docker network ls --filter name=cf-tunnel-net
  ```
- **Fix:**
  Ensure the shared network is marked `external: true` in your service's `docker-compose.yml`:
  ```yaml
  networks:
    cf-tunnel-net:
      external: true
  ```
  And declare `networks: [cf-tunnel-net]` under your service definition.

---

### 5. Bad, Expired, or Insufficient API Token

- **Symptom:** Sync daemon logs show `Cloudflare API Error (401): Unauthorized` or `403 Forbidden`.
- **Check:**
  Test token validity against Cloudflare Client API:
  ```bash
  curl -s -X GET "https://api.cloudflare.com/client/v4/user/tokens/verify" \
       -H "Authorization: Bearer <YOUR_CLOUDFLARE_API_TOKEN>"
  ```
- **Expected Outcome:**
  ```json
  {"result":{"id":"...","status":"active"},"success":true,"errors":[],"messages":[]}
  ```
- **Fix:**
  Create a new API Token in the Cloudflare dashboard with:
  - `Account → Cloudflare Tunnel → Edit`
  - `Zone → DNS → Edit`
  - `Zone → Zone → Read`

---

### 6. Tunnel Connector (`cloudflared`) Not Running or Token Missing

- **Symptom:** Cloudflare Zero Trust dashboard shows tunnel status `INACTIVE` / `DOWN`.
- **Check:**
  Check `cloudflared` container status:
  ```bash
  docker ps --filter name=cloudflared
  docker logs cloudflared --tail 30
  ```
- **Fix:**
  In single-compose or gateway setups, verify that the shared volume `cloudflared-token` is mounted by both `cf-tunnel-sync` and `cloudflared`. `cf-tunnel-sync` writes `tunnel-token.txt` and triggers a container restart for `cloudflared` upon first bootstrap.

---

### 7. Safety Guard / Blast-Radius Deletion Limit Tripped

- **Symptom:** Sync log outputs:
  `❌ BLAST RADIUS GUARD: Mass deletion threshold exceeded (planned: 4, limit: 3). Sync aborted.`
- **Check:**
  Inspect the ChangePlan details via API or dashboard:
  ```bash
  curl -s http://localhost:8080/api/status | grep safety_guard_tripped
  ```
- **Fix:**
  1. If containers stopped unexpectedly due to host reboot or maintenance, restart your service containers. `cf-tunnel-sync` safely preserved your DNS records without deleting them.
  2. If mass teardown is intentional, set `ALLOW_MASS_DELETIONS=true` in your `.env` and trigger sync:
     ```bash
     ALLOW_MASS_DELETIONS=true docker compose up -d
     ```

---

### 8. Dashboard HTTP 401 Unauthorized

- **Symptom:** Accessing `http://localhost:8080` prompts for credentials and rejects logins or returns 401.
- **Check:**
  Verify authentication configuration in `.env`:
  ```bash
  grep -E "(DASHBOARD_AUTH|BASIC_AUTH)" .env
  ```
- **Fix:**
  1. `cf-tunnel-sync` **fails closed** if `DASHBOARD_AUTH_ENABLED=true` but `DASHBOARD_PASSWORD` is blank or unconfigured.
  2. Set non-empty `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` in your `.env`:
     ```env
     DASHBOARD_AUTH_ENABLED=true
     DASHBOARD_USERNAME=admin
     DASHBOARD_PASSWORD=my_secure_password
     ```
  3. Restart the container:
     ```bash
     docker compose restart cf-tunnel-sync
     ```

---

### 9. Slow DNS Propagation

- **Symptom:** Record exists in Cloudflare DNS, but local resolver does not resolve it.
- **Check:**
  Query Cloudflare authoritative DNS resolver directly:
  ```bash
  dig @1.1.1.1 app.example.com CNAME
  ```
- **Fix:**
  `cf-tunnel-sync` creates CNAME records with `proxied: true` and Cloudflare automatic TTL (`1`), ensuring near-instant edge propagation. Local ISP resolvers may cache negative responses (NXDOMAIN) for up to 5 minutes; flush your local DNS cache or query `1.1.1.1` to confirm.
