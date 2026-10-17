# SAFE-02: Audit of Docker API Failure Handling & Fail-Closed Guards

**Audit Target:** `cf-tunnel-sync/app.py`, `cf-tunnel-sync/resilience.py`  
**Milestone:** M0 (Compatibility Baseline & Upgrade Safety - v1.14.0)  
**Tracking Issue:** [#90](https://github.com/hapheus/cf-docker-tunnel-sync/issues/90)  
**Date:** October 17, 2026  
**Status:** Completed & Formalized  

---

## 1. Executive Summary

This audit examines the container discovery pipeline across Unix domain socket communications, Docker API response processing, and network partition scenarios. The core requirement is that any failure, timeout, socket disconnect, or incomplete container inventory must cause the system to **fail closed**—meaning zero destructive mutations against Cloudflare DNS or Tunnel ingress rules.

---

## 2. Current Discovery Pipeline Analysis

### 2.1 Socket Communication & Exception Handling
In `app.py` (`get_docker_containers` / `_query_docker_socket`):
* Discovery communicates directly with the Docker daemon via Unix socket (`/var/run/docker.sock`).
* When the Docker daemon is unreachable, restarts, or times out:
  * Connection errors (`socket.error`, `FileNotFoundError`) raise `DockerAPIError`.
  * HTTP status errors (e.g., `403 Forbidden` from misconfigured socket proxies) raise `DockerAPIError`.
  * Timeouts (`socket.timeout`) raise `DockerAPIError`.

### 2.2 Reconcile Engine Guard (`docker_ok`)
In `reconcile.py`:
* The state of Docker inventory is passed via `DiscoverySnapshot(timestamp=..., docker_ok=..., origins=...)`.
* When `docker_ok is False`:
  * `compute_change_plan` refuses to plan any deletions or updates.
  * The cycle terminates with zero mutations (`has_mutations: False`).
  * Cloudflare remote state is preserved completely intact.

### 2.3 Blast-Radius Safeguards
* **`MAX_DELETIONS_PER_SYNC` (Default: 5):**
  * Prevents accidental mass route wipes if an anomalous empty inventory somehow bypasses initial checks.
* **`ALLOW_MASS_DELETIONS` (Default: False):**
  * Requires explicit operator opt-in to execute more than 5 deletions in a single sync run.
* **`cf_tunnel_safety_guard_tripped` Metric:**
  * Incremented whenever the blast-radius ceiling is exceeded.

---

## 3. Findings & Identified Edge Cases

### Finding 1: Transient Daemon Restart & Empty Inventory Window
* **Scenario:** The Docker daemon restarts or crashes. During startup, the socket may become responsive before all container runtimes have initialized.
* **Behavior:** Docker API returns an empty JSON list `[]` with HTTP `200 OK`. `docker_ok` would be `True`, but 0 containers are discovered.
* **Current Mitigation:**
  * `RECONCILE_GRACE_PERIOD_SECONDS` (default 60s) records tombstones and defers any DNS or Ingress deletion until the grace window has elapsed.
  * If the number of removed containers exceeds `MAX_DELETIONS_PER_SYNC` (5), `BlastRadiusExceededError` trips and completely blocks execution.

### Finding 2: Socket Proxy Authority & GET-Only Constraints
* Mounting `/var/run/docker.sock:ro` in read-only mode prevents container processes from modifying the filesystem socket node, but does **not** restrict API calls sent over that socket.
* The daemon requires only read operations (`GET /containers/json`, `GET /events`).
* **Milestone 2 Invariant:** Validate and document supported rootless Docker socket proxies (e.g., `tecnativa/docker-socket-proxy`) with restricted permissions (`CONTAINERS=1`, `EVENTS=1`).

---

## 4. Invariants for Milestone 2 Implementation

1. **Fail-Closed Invariant:** If `get_docker_containers()` encounters any socket error, EOF, or HTTP status >= 400, `docker_ok` MUST be set to `False`, and reconciliation MUST abort with zero mutations.
2. **Empty-Inventory Sudden Drop Invariant:** If previous sync discovered $N \ge 2$ services and current sync discovers $0$ services, the change plan must require confirmation through the full grace period before acting, logging a high-priority warning.
3. **Observability Invariant:** Every Docker discovery failure must emit an event to `/api/status`, log a structured error, and increment `cf_tunnel_errors_total{error_type="docker_api"}`.
