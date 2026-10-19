# Product scope

`cf-docker-tunnel-sync` manages Cloudflare Tunnel ingress and DNS for services discovered from standalone Docker containers and Docker Compose stacks.

The synchronizer reads labels and lifecycle events, computes configuration changes, and uses the Cloudflare API to apply them. It also provides status, diagnostic information, metrics, and an optional dashboard. The separate `cloudflared` process carries application traffic.

## Included

- Hostname-based service discovery and origin routing configuration.
- Named remotely managed tunnel initialization and connector token sharing.
- CNAME creation and cleanup, ownership classification, grace periods, and deletion guards.
- Single-stack or separate application/gateway stacks, including tunnel-name scoping.
- Headless status/API access and embedded or companion dashboard presentation.

See [architecture and safety](architecture-and-safety.md) for the actual behavior and its limitations.

## Outside the current scope

The project does not replace a LAN reverse proxy, terminate origin TLS, administer host firewalls, or manage arbitrary DNS providers. It does not act as a Kubernetes/Swarm ingress controller or maintain WAF rules.

Cloudflare Access-policy authoring is also outside the current scope. Access labels are status metadata, not an authorization mechanism. Configure application authentication or Cloudflare Access separately.

For contributor workflow and feature proposals, see [Contributing](../CONTRIBUTING.md).
