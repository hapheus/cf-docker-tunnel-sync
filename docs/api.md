# HTTP API Reference & Contract Specification

This document provides the authoritative specification for all public HTTP endpoints, authentication protocols, and response schemas exposed by `cf-tunnel-sync`.

---

## 🏛️ Architecture & Responsibility Separation

`cf-docker-tunnel-sync` follows a strict client-server decoupling between the sync engine backend and web presentation clients:

- **Sync Backend (`cf-tunnel-sync`):**  
  Owns Docker daemon inspection, container label parsing, network reachability preflight, reconciliation state-machine computation, Cloudflare API interaction, and secret masking. Exposes operational data via a documented, frozen HTTP REST API on port `8090` (typically mapped to host `8080:8090`).
- **Dashboard Clients:**  
  Read-only consumers that interact with the sync engine **exclusively via HTTP**. Dashboard clients never mount the Docker socket (`/var/run/docker.sock`), never access Cloudflare API tokens, and never inspect private internal state.  
  Two dashboard distribution modes are supported with 100% feature parity:
  1. **Embedded Dashboard (`/` & `/dashboard`):** Served directly by the sync daemon when `DASHBOARD_ENABLED=true` (default for seamless single-container deployments).
  2. **Standalone Companion Dashboard (`hapheus/cf-tunnel-dashboard`):** An independent lightweight Nginx container proxying `/api/*` to the sync backend via `SYNC_BACKEND_HOST` and `SYNC_BACKEND_PORT`.

---

## 🔐 Authentication Modes

API and dashboard routes enforce authentication based on `DASHBOARD_AUTH_ENABLED`, `DASHBOARD_USERNAME`, and `DASHBOARD_PASSWORD` (`BASIC_AUTH_USERNAME` and `BASIC_AUTH_PASSWORD` aliases are fully supported).

| Mode | Configuration | Behavior |
| :--- | :--- | :--- |
| **Unauthenticated (Default Single-Compose)** | `DASHBOARD_AUTH_ENABLED=false` or unset with empty credentials | All endpoints accessible without credentials. |
| **Fail-Closed Basic Auth** | `DASHBOARD_AUTH_ENABLED=true` with blank/missing credentials | **Rejects all requests with HTTP 401** and `WWW-Authenticate: Basic realm="Cloudflare Tunnel Sync Dashboard"`. Protects against accidental exposure when credentials fail to load. |
| **Active Basic Auth** | `DASHBOARD_AUTH_ENABLED=true` with username & password set | Requires `Authorization: Basic <base64>` header matching configured credentials. |

> ℹ️ **Public Probes:**  
> The liveness probe (`GET /health`), readiness probe (`GET /ready`), and Prometheus scraper (`GET /metrics`) are public unauthenticated diagnostic endpoints designed for container orchestrators and monitoring agents.

---

## 📡 Endpoints Reference

### 1. Health & Readiness Probes

#### `GET /health` & `GET /healthz`
Returns daemon operational health and Docker connection status.

- **Auth:** None (Public)
- **Status Code:** `200 OK`
- **Response Schema (`application/json`):**
  ```json
  {
    "status": "healthy",
    "docker_connected": true,
    "sync_status": "Synced (1 active)"
  }
  ```
  *(Note: `status` evaluates to `"healthy"` when `docker_connected` is `true`, or `"degraded"` when Docker is disconnected).*

#### `GET /ready`
Readiness probe for load balancers and orchestrator rollouts.

- **Auth:** None (Public)
- **Status Codes:**
  - `200 OK`: Sync engine initialized and Docker daemon connected.
  - `503 Service Unavailable`: Docker daemon disconnected or unreachable.
- **Response Schema (`application/json`):**
  ```json
  {
    "status": "ready",
    "docker_connected": true,
    "sync_status": "Synced"
  }
  ```

---

### 2. Metrics & Telemetry

#### `GET /metrics`
Exposes system and reconciliation metrics in Prometheus text exposition format (version 0.0.4).

- **Auth:** None (Public)
- **Content-Type:** `text/plain; version=0.0.4; charset=utf-8`
- **Sample Output:**
  ```text
  # HELP cf_tunnel_sync_containers_managed Current number of containers managed by tunnel sync
  # TYPE cf_tunnel_sync_containers_managed gauge
  cf_tunnel_sync_containers_managed 2.0
  # HELP cf_tunnel_sync_reconcile_total Total number of reconciliation cycles executed
  # TYPE cf_tunnel_sync_reconcile_total counter
  cf_tunnel_sync_reconcile_total{status="success"} 42.0
  ```

---

### 3. Master Status & Operational State

#### `GET /api/status`
Returns the complete operational sync state, discovered services, redacted credentials, and diagnostic pipeline results.

- **Auth:** Subject to `check_dashboard_auth`
- **Status Code:** `200 OK`
- **Response Schema (`application/json`):**
  ```json
  {
    "status": "Active (Synced)",
    "domain_name": "example.com",
    "tunnel_name": "production-gateway",
    "tunnel_id": "8a7b6c5d-4e3f-2a1b-0c9d-8e7f6a5b4c3d",
    "zone_id": "0123456789abcdef0123456789abcdef",
    "account_id": "0123456789abcdef0123456789abcdef",
    "docker_connected": true,
    "last_sync": "2026-10-18T10:15:00Z",
    "services": {
      "app-service": {
        "hostname": "app.example.com",
        "service": "http://app-service:8080",
        "status": "Active",
        "container_name": "app-service",
        "container_id": "c1a2b3c4d5e6",
        "networks": ["cf-tunnel-net"]
      }
    },
    "logs": [
      "2026-10-18 10:15:00 [INFO] Synchronization completed successfully."
    ],
    "diagnostics": {
      "overall_status": "Healthy",
      "stages": {}
    },
    "dry_run": false
  }
  ```
- **Security Guarantee:** All internal state fields beginning with an underscore (`_`) are filtered out. API tokens, passwords, and sensitive headers are guaranteed redacted as `"[REDACTED]"`.

---

### 4. Reconciliation Change Plan & Preview

#### `GET /api/change-plan`
Exposes the structured execution plan computed by the state-machine reconciler.

- **Auth:** Subject to `check_dashboard_auth`
- **Status Code:** `200 OK`
- **Response Schema (`application/json`):**
  ```json
  {
    "plan_id": "plan-a521aea69a53",
    "dry_run": false,
    "timestamp": 1792311968.724888,
    "actions": [
      {
        "action": "CREATE",
        "resource": "DNS",
        "target": {
          "hostname": "app.example.com",
          "record_type": "CNAME",
          "target_content": "8a7b6c5d.cfargotunnel.com",
          "proxied": true,
          "ttl": 1
        },
        "reason": "Container discovered with ingress label"
      }
    ],
    "summary": {
      "additions": 1,
      "updates": 0,
      "deletions": 0,
      "unmanaged_skipped": 0
    }
  }
  ```

#### `GET /api/sync/preview` & `GET /api/v1/sync/preview`
Computes an on-demand, non-mutating preview of what changes would be applied given the current live container inventory.

- **Auth:** Subject to `check_dashboard_auth`
- **Status Code:** `200 OK`
- **Response Schema (`application/json`):**
  ```json
  {
    "status": "cached" | "computed",
    "plan": { ... }
  }
  ```

---

### 5. Manual Synchronization Trigger

#### `POST /api/sync`
Triggers an immediate asynchronous reconciliation cycle, bypassing the periodic polling timer.

- **Auth:** Subject to `check_dashboard_auth`
- **Status Code:** `200 OK`
- **Response Schema (`application/json`):**
  ```json
  {
    "message": "Sync triggered",
    "state": { ... }
  }
  ```

---

### 6. Embedded Web Interface

#### `GET /` & `GET /dashboard`
Serves the embedded single-page dashboard application.

- **Auth:** Subject to `check_dashboard_auth`
- **Content-Type:** `text/html; charset=utf-8`
- **Security Headers:**
  - `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self';`
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
- **Headless Mode (`DASHBOARD_ENABLED=false`):**
  Returns `404 Not Found` with JSON message `{"status": "disabled", "message": "Embedded dashboard UI is disabled. Use /api/status for API data."}` while all `/api/*` endpoints remain fully active.
