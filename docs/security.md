# Security Architecture & Hardening Guide

This document outlines the security invariants, threat boundaries, and recommended hardening procedures for `cf-docker-tunnel-sync`.

---

## 1. Docker Socket Privileges & Threat Model (SEC-01)

### 1.1 The `/var/run/docker.sock:ro` Bind Mount
By default, Docker Compose configurations mount the Docker Unix socket into the `cf-tunnel-sync` container:
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```
**Important Security Context:**
- The `:ro` (read-only) mount flag prevents container processes from modifying, deleting, or recreating the socket inode on the host filesystem.
- However, the `:ro` flag does **not** restrict HTTP REST API operations sent *across* the socket connection. An attacker with arbitrary code execution inside a container with Docker socket access can issue read requests (`GET /containers/json`, `GET /events`), which allows inspecting container environment variables and configurations across the entire Docker host.

### 1.2 Mitigation: Read-Only Socket Proxy
For production environments, shared infrastructure, or hardened homelabs, use an isolated Docker socket proxy (such as [`tecnativa/docker-socket-proxy`](https://github.com/Tecnativa/docker-socket-proxy)) to enforce least-privilege API access.

`cf-tunnel-sync` only requires two endpoints:
- `GET /containers/json` (container discovery)
- `GET /events` (event-driven sync)

#### Hardened Socket Proxy Architecture:
```
[cf-tunnel-sync] ---> TCP:2375 ---> [docker-socket-proxy] ---> /var/run/docker.sock ---> [Docker Engine]
                                      • CONTAINERS=1 (read-only)
                                      • EVENTS=1 (read-only)
                                      • POST=0 (blocked)
                                      • BUILD=0, EXEC=0 (blocked)
```

#### Example Configuration:
A fully configured, working example is provided in [examples/04-socket-proxy/docker-compose.yml](../examples/04-socket-proxy/docker-compose.yml):
```yaml
services:
  docker-socket-proxy:
    image: tecnativa/docker-socket-proxy:latest
    container_name: docker-socket-proxy
    restart: unless-stopped
    environment:
      - CONTAINERS=1
      - EVENTS=1
      - POST=0
      - NETWORKS=0
      - VOLUMES=0
      - SERVICES=0
      - SWARM=0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - socket-proxy-net

  cf-tunnel-sync:
    image: hapheus/cf-tunnel-sync:latest
    container_name: cf-tunnel-sync
    restart: unless-stopped
    environment:
      - DOCKER_HOST=tcp://docker-socket-proxy:2375
      - CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}
      - DOMAIN_NAME=${DOMAIN_NAME}
    networks:
      - cf-tunnel-net
      - socket-proxy-net
```

---

## 2. Credential Redaction & Log Sanitization (SEC-02)

`cf-tunnel-sync` incorporates automated regex-based redaction across all operational boundaries:
1. **Log Streams & Status APIs:**
   - Authorization headers (`Bearer [REDACTED]`)
   - Cloudflare API tokens and tunnel secrets (`[REDACTED_JWT_TOKEN]`)
   - Webhook URLs (Discord, Slack, and generic webhooks) have tokens and paths masked (`https://discord.com/api/webhooks/[REDACTED]`, `https://hooks.slack.com/services/[REDACTED]`)
2. **Dashboard Status API (`/api/status`):**
   - Private internal state keys (prefixed with `_`) are filtered out before serialization.
   - Sensitive credential keys (`token`, `secret`, `password`, `key`) are automatically redacted to `[REDACTED]`.
3. **Notification Payloads:**
   - Webhook titles, messages, and structured details dictionaries are sanitized prior to dispatch.

---

## 3. Strict Resource Ownership Invariants (SAFE-01)

To prevent route hijacking, domain collisions, or accidental deletion of foreign records:
- **Stateless Ownership Tagging:** Every DNS record created or managed by `cf-tunnel-sync` carries a metadata comment in Cloudflare DNS: `cf-tunnel-sync:<tunnel_name>`.
- **Pre-Existing Record Protection:** CNAME, A, or TXT records created manually or by other tools that lack this tunnel's comment tag are classified as `UNMANAGED`, `FOREIGN_TUNNEL`, or `UNRELATED`. They are **never** modified or deleted by `cf-tunnel-sync`.
- **Destructive Operation Preconditions:** A Cloudflare DNS record is eligible for automated deletion **only** if:
  1. Its type is `CNAME`.
  2. Its content matches `tunnel_id.cfargotunnel.com`.
  3. Its comment matches `cf-tunnel-sync:<tunnel_name>` (exact match).

---

## 4. Blast-Radius Safeguards & Fail-Closed Guardrails (SAFE-02 / SAFE-07)

1. **Docker Daemon Degradation:** If the Docker daemon disconnects, times out, or returns HTTP 5xx errors, discovery snapshot sets `docker_ok=False`. The reconciler immediately **fails closed**: zero writes, zero updates, zero deletes.
2. **Sudden Container Inventory Drop:** If previous sync cycles discovered 2 or more services, and the current cycle discovers 0 services (e.g., during a Docker daemon restart or compose reload), `cf-tunnel-sync` logs a high-priority safety warning and enforces the full tombstone grace period (`DNS_CLEANUP_GRACE_PERIOD`), preventing mass route wipeout.
3. **Mass Deletion Ceiling:**
   - `MAX_DELETIONS_PER_SYNC` (default: 3) limits the maximum number of route deletions in a single sync cycle.
   - Exceeding the threshold trips `BlastRadiusExceededError` and marks the sync state as `SAFETY_GUARD_TRIPPED`.
   - Even when `ALLOW_MASS_DELETIONS=true` is explicitly configured, unmanaged and foreign records remain strictly protected.
