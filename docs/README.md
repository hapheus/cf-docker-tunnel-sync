# Documentation

`cf-docker-tunnel-sync` connects Docker services to Cloudflare Tunnel by reading container labels and updating ingress rules and DNS. The `cloudflared` connector carries application traffic; the synchronizer manages configuration.

## Get started

- [Quickstart](../QUICKSTART.md): set up a gateway and a demo service.
- [Expose an existing service](onboarding.md): add an application to an existing gateway.
- [Cloudflare API token](cloudflare-permissions.md): create a scoped token.
- [Deployment examples](../examples/): single-stack, separate stacks, socket proxy, and multiple gateways.

## Configure

- [Environment variables](configuration.md): defaults, precedence, and deployment settings.
- [Container labels](labels.md): hostnames, ports, protocols, and origin TLS settings.
- [Docker networking](networking-guide.md): shared networks and the request path.

## Operate

- [Operations](operations.md): status, logs, metrics, recovery, and removal.
- [Troubleshooting](troubleshooting.md): DNS, unreachable services, authentication, and safety guards.
- [Upgrade and rollback](COMPATIBILITY.md): update an existing deployment.
- [Container releases](release-security.md): image tags, digests, and artifact verification.

## Understand and integrate

- [HTTP API](api.md): endpoints, authentication, and response formats.
- [Architecture and safety](architecture-and-safety.md): reconciliation, ownership, and current limitations.
- [Security](security.md): Docker socket access, credentials, and exposure.
- [Support and prerequisites](support-matrix.md): build targets and operational boundaries.
- [Product scope](product-boundaries.md): what the project manages.

These pages describe the current implementation. In particular, Access labels are metadata rather than access controls, and dry-run performs no external writes, including tunnel initialization. Read the [current safety limitations](architecture-and-safety.md#current-limitations) before attaching an existing tunnel.
