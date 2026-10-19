# Deployment examples

Choose an example for your Docker Compose setup. Each gateway needs a scoped Cloudflare token, a zone you control, outbound connectivity for `cloudflared`, and Docker access for discovery. Starting it can create a tunnel and modify ingress/DNS; see the [current safety limitations](../docs/architecture-and-safety.md#current-limitations).

| Example | What you can try |
| --- | --- |
| [Single stack](01-quickstart-single-stack/README.md) | Gateway, connector, and an HTTP whoami demo in one Compose file. |
| [Separate stacks](02-multi-stack-external-net/README.md) | A gateway and an independent application sharing an external network; optional companion dashboard. |
| [Socket proxy](03-secure-socket-proxy/README.md) | Restrict Docker access to reads and handle connector restarts manually. |
| [TLS, headers, and ports](04-advanced-labels-tls-multiport/README.md) | Real HTTPS whoami origins with a locally generated certificate and an Nginx origin listening on two ports. |
| [Two gateways](05-multi-account/README.md) | Separate credentials, domains, connector names, networks, token volumes, and dashboard ports. |

## Before starting

Copy the selected directory's `.env.example` to `.env`, then replace its token/domain and any password placeholders. Files next to a Compose variant apply to that variant; the repository-root `.env` is not a global configuration for every example.

Each README lists prerequisites and verification commands. Floating image tags make the examples easy to try; choose published versions/digests for repeatable deployment. Successful YAML/model checks alone do not establish that images were pulled or routing works on your host.

Examples 01–04 use fixed container names and the default network `cf-tunnel-net`. Treat them as alternative standalone setups rather than starting all of them together. Example 05 is designed for simultaneous gateways; use unique names and ports when adding more instances. Avoid a Compose project-name override that would make separate stacks share a project/volume accidentally.

## Connector startup

Every gateway shares `/etc/cloudflared/token` between the synchronizer and connector. The connector mounts it read-only and runs with `--token-file /etc/cloudflared/token`; you do not copy a token manually.

These example Compose healthchecks require both a nonempty token file and a successful local `/health` request before Compose starts the connector. This is stronger than the image's default healthcheck, but does not establish a successful remote sync or origin reachability. Review logs and public application responses after startup.

The socket proxy blocks automatic restart POSTs. Other examples let the synchronizer attempt a restart after writing a changed token. See [operations](../docs/operations.md) for lifecycle and cleanup; stopping the gateway does not automatically remove Cloudflare resources.
