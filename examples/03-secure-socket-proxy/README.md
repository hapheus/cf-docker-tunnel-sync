# 🛡️ Example 03: Secure Docker Socket Proxy Setup

This example demonstrates how to harden `cf-docker-tunnel-sync` using a dedicated, read-only Docker socket proxy (`tecnativa/docker-socket-proxy`), eliminating any direct volume mount of `/var/run/docker.sock` into the sync container.

---

## Why Mount `:ro` on `/var/run/docker.sock` is Not Truly Read-Only

A common misconception in Docker deployments is that mounting the Unix socket with `:ro` (`/var/run/docker.sock:/var/run/docker.sock:ro`) provides read-only security.

In Unix domain sockets, `:ro` only prevents **re-binding or replacing the filesystem socket node**. It **does not prevent sending HTTP POST/DELETE mutation requests** through the open socket stream. Anyone with access to the socket stream can still execute Docker commands (`docker run`, `docker exec`, container creation, host filesystem mounts).

---

## The Solution: HTTP REST API Filtering

By placing a socket proxy between Docker and `cf-tunnel-sync`:
1. Only `GET /containers/json` (`CONTAINERS=1`) and `GET /events` (`EVENTS=1`) are permitted.
2. All mutation endpoints (`POST=0`, `DELETE=0`, `EXEC=0`, `NETWORKS=0`, `SWARM=0`) are permanently rejected with HTTP 403 Forbidden.
3. `cf-tunnel-sync` communicates over an internal, non-routable Docker network via `DOCKER_HOST=tcp://docker-socket-proxy:2375`.

---

## How to Run

1. Copy the environment file:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` with your credentials:
   ```env
   CLOUDFLARE_API_TOKEN=your_token_here
   DOMAIN_NAME=example.com
   ```
3. Start the secured stack:
   ```bash
   docker compose up -d
   ```
