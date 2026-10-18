# 🔒 Example 04: Hardened Docker Socket Proxy Setup

This example demonstrates how to run `cf-docker-tunnel-sync` **without mounting `/var/run/docker.sock` directly** into the sync container.

## How it works

1. `docker-socket-proxy` (`tecnativa/docker-socket-proxy`) mounts `/var/run/docker.sock:ro` on an internal Docker bridge network (`socket-proxy-net`).
2. The proxy strictly filters the Docker Engine REST API, allowing only:
   - `GET /containers/json` (`CONTAINERS=1`)
   - `GET /events` (`EVENTS=1`)
   - All mutation endpoints (`POST=0`, `DELETE=0`, `EXEC=0`) are permanently disabled.
3. `cf-tunnel-sync` communicates with the proxy via TCP: `DOCKER_HOST=tcp://docker-socket-proxy:2375`.

## Usage

```bash
docker compose up -d
```
