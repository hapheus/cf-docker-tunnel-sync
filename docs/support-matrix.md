# Prerequisites and support boundaries

The project targets standalone Docker Engine and Docker Compose running Linux containers, with a remotely managed Cloudflare Tunnel and a DNS zone accessible to the sync token.

## Platforms and build targets

| Environment | Evidence and boundary |
| --- | --- |
| Linux amd64 | Targeted by the image publish workflow. |
| Linux arm64 | Targeted by the image publish workflow. |
| Linux armv7 / 32-bit ARM | Not targeted by the current publish workflow; no prebuilt-image support is established here. |
| macOS Docker Desktop / OrbStack | Linux-container environments may be suitable for development; the repository does not establish a complete host/version compatibility matrix. |
| Windows with WSL2 Linux containers | Same qualification as other Linux-container VM environments. Native Windows containers are outside scope. |
| Kubernetes / Swarm | Outside the supported discovery model; this is a standalone Docker/Compose controller. |

Build targets describe workflow configuration, not verified availability or functionality of every registry artifact. Check the selected image manifest for your architecture.

Use Docker Compose v2 (`docker compose`). This repository does not establish a tested minimum Engine/Compose version across all examples. Verify support for the features in your chosen file, including external networks, interpolation, and health-based startup dependencies.

## Cloudflare and networking

- A Cloudflare zone matching `DOMAIN_NAME` and a token with [tunnel edit, DNS edit, and zone read](cloudflare-permissions.md) access.
- A remotely managed named tunnel. Normal startup creates a missing tunnel by name.
- A running `cloudflared` connector with a readable shared token file and outbound connectivity to Cloudflare.
- A reachable origin address/port from the connector, usually through a shared Docker bridge network.

An Access subscription or metadata label is not a substitute for actual application authorization. Consult Cloudflare's own product documentation for current account limits and pricing; those values are not maintained here.

## Operational boundaries

The controller does not proxy application traffic. HTTP/HTTPS examples are the primary walkthroughs; parsing other origin schemes does not establish all required Cloudflare client/protocol setup.

The service has cleanup grace periods and deletion limits, with [known limitations](architecture-and-safety.md#current-limitations). Configuration diagnostics assess plausibility and do not prove public reachability. A GET-only socket proxy blocks automatic connector restart.

For settings and aliases, use [configuration](configuration.md) and [labels](labels.md). For updates, use [upgrade and rollback](COMPATIBILITY.md).
