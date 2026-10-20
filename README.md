<div align="center">

# ☁️ cf-docker-tunnel-sync

[![GitHub Release](https://img.shields.io/github/v/release/hapheus/cf-docker-tunnel-sync?style=flat-square&color=blue)](https://github.com/hapheus/cf-docker-tunnel-sync/releases)
[![Docker Pulls](https://img.shields.io/docker/pulls/hapheus/cf-tunnel-sync?style=flat-square)](https://hub.docker.com/r/hapheus/cf-tunnel-sync)
[![Docker Image Size](https://img.shields.io/docker/image-size/hapheus/cf-tunnel-sync/latest?style=flat-square)](https://hub.docker.com/r/hapheus/cf-tunnel-sync)
[![GitHub Stars](https://img.shields.io/github/stars/hapheus/cf-docker-tunnel-sync?style=flat-square)](https://github.com/hapheus/cf-docker-tunnel-sync/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

[![CI Status](https://img.shields.io/github/actions/workflow/status/hapheus/cf-docker-tunnel-sync/ci.yml?branch=main&style=flat-square)](https://github.com/hapheus/cf-docker-tunnel-sync/actions)
[![Daily Live Image Verification](https://github.com/hapheus/cf-docker-tunnel-sync/actions/workflows/daily-image-verification.yml/badge.svg)](https://github.com/hapheus/cf-docker-tunnel-sync/actions/workflows/daily-image-verification.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/hapheus/cf-docker-tunnel-sync/badge)](https://scorecard.dev/viewer/?uri=github.com/hapheus/cf-docker-tunnel-sync)
[![OpenSSF Best Practices](https://img.shields.io/cii/percentage/15662?style=flat-square&logo=linuxfoundation&label=OpenSSF%20Best%20Practices)](https://www.bestpractices.dev/projects/15662)

[Quickstart](QUICKSTART.md) · [Documentation](docs/README.md) · [Examples](examples/) · [Contributing](CONTRIBUTING.md)

</div>

Synchronize Docker container labels with Cloudflare Tunnel ingress and proxied DNS CNAME records. The Python controller manages configuration; the separate `cloudflared` connector carries traffic to applications on a reachable Docker network.

## How it works

Give a running application a hostname and its internal port, then attach it to the connector's network:

```yaml
services:
  web:
    image: nginx:alpine
    networks:
      - cf-tunnel-net
    labels:
      cf.tunnel.hostname: web.example.com
      cf.tunnel.port: "80"

networks:
  cf-tunnel-net:
    external: true
```

The gateway discovers the service through Docker events and periodic reconciliation, updates its named tunnel, and manages the corresponding CNAME. The default fallback interval is 900 seconds; events use a 2.5-second debounce window. No application host-port mapping is required for tunnel traffic.

The controller can initialize a tunnel, write the connector token to a shared volume, and attempt a connector restart. It exposes status, logs, metrics, and an embedded dashboard. A separate Nginx dashboard is optional; headless deployments do not need published API ports.

## Before using existing resources

Use a dedicated tunnel and a scoped token. Ownership comments, grace periods, and deletion limits reduce accidental cleanup, but current behavior has important boundaries:

- Dry-run performs reads and planning only: it does not create a tunnel, write its token, or restart the connector. A missing tunnel is reported as a prerequisite.
- Manual ingress paths, duplicate rules, catch-alls, and their relative order are preserved. The first root route for an actively discovered hostname is managed by the synchronizer.
- Missing, empty, or null DNS comments do not establish ownership. The default policy can adopt matching untagged records for active services.
- Access labels are status metadata and do not configure authentication.

Read [architecture and safety](docs/architecture-and-safety.md) and [security](docs/security.md) before connecting an existing deployment. Use `--preflight` for non-mutating inspection; it still reads configured Docker and Cloudflare resources.

## Deployment choices

| Example | Purpose |
| --- | --- |
| [Single stack](examples/01-quickstart-single-stack/README.md) | Gateway, connector, and demo application together. |
| [Separate stacks](examples/02-multi-stack-external-net/README.md) | One gateway network shared by independent application stacks. |
| [Socket proxy](examples/03-secure-socket-proxy/README.md) | Restrict Docker API access; automatic restart is blocked. |
| [Origin settings](examples/04-advanced-labels-tls-multiport/README.md) | HTTPS origins, custom headers, and explicit port selection. |
| [Multiple gateways](examples/05-multi-account/README.md) | Separate domains, tokens, connector targets, and volumes. |

The root Compose file publishes the embedded dashboard on host port 8080 and enables authentication by default. The [Quickstart](QUICKSTART.md) uses a headless gateway instead. See [configuration](docs/configuration.md) before changing ports or environment values.

## Dashboard

| Desktop | Mobile |
| --- | --- |
| ![Dashboard overview](docs/screenshots/dashboard-preview.png) | ![Dashboard on a narrow display](docs/screenshots/dashboard-mobile.png) |

Screenshots illustrate the UI; status reflects controller observations rather than an independent end-to-end application health check.

## License

[MIT](LICENSE).
