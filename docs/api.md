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
| **Prometheus Scraper Auth** | `METRICS_AUTH_ENABLED=true` with username & password set | Secures `GET /metrics` with HTTP Basic Authentication (`Basic realm="Prometheus Metrics"`). Defaults to `false` for 100% backward compatibility with unauthenticated scrapers. |

> ℹ️ **Public Probes:**  
> The liveness probe (`GET /health`), readiness probe (`GET /ready`), and Prometheus scraper (`GET /metrics`, when `METRICS_AUTH_ENABLED=false`) are public unauthenticated diagnostic endpoints designed for container orchestrators and monitoring agents.

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

- **Auth:** Unauthenticated by default; requires Basic Auth when `METRICS_AUTH_ENABLED=true` (reusing `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`).
- **Content-Type:** `text/plain; version=0.0.4; charset=utf-8`
- **Sample Output:**
  ```text
  # HELP cf_tunnel_sync_runs_total Total count of synchronization loop runs
  # TYPE cf_tunnel_sync_runs_total counter
  cf_tunnel_sync_runs_total{status="success"} 42.0
  # HELP cf_tunnel_sync_duration_seconds Duration in seconds of the most recent sync execution
  # TYPE cf_tunnel_sync_duration_seconds gauge
  cf_tunnel_sync_duration_seconds 0.125
  # HELP cf_tunnel_sync_last_success_timestamp Unix timestamp of the most recent successful sync completion
  # TYPE cf_tunnel_sync_last_success_timestamp gauge
  cf_tunnel_sync_last_success_timestamp 1792311968.0
  # HELP cf_tunnel_dns_operations_total Total DNS operations by type (create, update, delete, protect)
  # TYPE cf_tunnel_dns_operations_total counter
  cf_tunnel_dns_operations_total{operation="create"} 5.0
  # HELP cf_tunnel_docker_connected 1 if Docker daemon is connected, 0 otherwise
  # TYPE cf_tunnel_docker_connected gauge
  cf_tunnel_docker_connected 1.0
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
    "overview_metrics": {
      "active_services": 1,
      "discovered_services": 1,
      "failed_services": 0,
      "last_sync_duration_ms": 124.5,
      "safety_tripped": false,
      "api_connected": true,
      "health_state": "healthy"
    },
    "alert_status": {
      "configured": true,
      "provider": "discord",
      "last_delivery_success": true,
      "last_delivery_time": 1792311900.0,
      "consecutive_failures": 0,
      "cooldown_active": false
    },
    "sync_history": [],
    "events": [],
    "diagnostics": {
      "overall_status": "Healthy",
      "stages": {}
    },
    "dry_run": false
  }
  ```
- **Security Guarantee:** All internal state fields beginning with an underscore (`_`) are filtered out. API tokens, passwords, and sensitive headers are guaranteed redacted as `"[REDACTED]"`.

---

### 4. Audit Events, History & Alerts

#### `GET /api/events`
Exposes the bounded structured event timeline with optional query filters (Issue #120).

- **Auth:** Subject to `check_dashboard_auth`
- **Query Parameters:**
  - `limit` (int, default `100`, max `100`): Maximum entries to return.
  - `severity` (string, optional): Filter by `info`, `warning`, or `error`.
  - `service` (string, optional): Filter by target service name or container hostname.
  - `q` (string, optional): Search query matched against message text, event type, or service.
- **Status Code:** `200 OK`
- **Response Schema (`application/json`):**
  ```json
  {
    "events": [
      {
        "id": "evt-1792311968000-a1b2c3",
        "timestamp": 1792311968.0,
        "iso_time": "2026-10-18T10:15:00.000000+00:00",
        "severity": "info",
        "event_type": "DNS_CREATE",
        "service": "app.example.com",
        "message": "Created DNS CNAME record for app.example.com"
      }
    ],
    "total": 1
  }
  ```

#### `GET /api/history`
Exposes the bounded ring-buffer (up to 20 entries) of historical sync cycle durations, completion statuses, and discovered service counts (Issue #119).

- **Auth:** Subject to `check_dashboard_auth`
- **Query Parameters:**
  - `limit` (int, default `20`, max `20`): Maximum entries to return.
- **Status Code:** `200 OK`
- **Response Schema (`application/json`):**
  ```json
  {
    "history": [
      {
        "timestamp": 1792311968.0,
        "iso_time": "2026-10-18T10:15:00.000000+00:00",
        "duration_ms": 125.4,
        "status": "Active / Synced",
        "services_count": 2,
        "summary": {
          "total_services_discovered": 2,
          "dns_creates": 0,
          "dns_updates": 0,
          "dns_deletes": 0
        }
      }
    ],
    "total": 1
  }
  ```

#### `GET /api/notifications/status`
Exposes webhook notification dispatch telemetry, delivery outcomes, and cooldown status without revealing webhook secrets (Issue #121).

- **Auth:** Subject to `check_dashboard_auth`
- **Status Code:** `200 OK`
- **Response Schema (`application/json`):**
  ```json
  {
    "configured": true,
    "provider": "discord",
    "last_delivery_success": true,
    "last_delivery_time": 1792311900.0,
    "last_delivery_status": "HTTP 204 No Content",
    "consecutive_failures": 0,
    "cooldown_active": false,
    "cooldown_seconds": 300.0
  }
  ```

---

### 5. Reconciliation Change Plan & Preview

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
