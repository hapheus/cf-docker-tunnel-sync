# Documentation Index

`cf-docker-tunnel-sync` manages Cloudflare Tunnel ingress rules and DNS CNAME records automatically based on Docker container labels. The `cloudflared` connector carries encrypted tunnel traffic; `cf-tunnel-sync` handles the configuration lifecycle.

Use this index to find guides, configuration references, and operational documentation.

---

## 🚀 Getting Started

Step-by-step guides for installing and exposing your first applications:

- **[Quickstart Guide](../QUICKSTART.md):** Minimal 60-second walkthrough with Docker Compose and demo service (`whoami`).
- **[Onboarding Existing Services](onboarding.md):** How to attach existing Docker services to the tunnel network and label them.
- **[Cloudflare Token Permissions](cloudflare-permissions.md):** How to create a least-privilege Cloudflare API token.
- **[Deployment Examples](../examples/):**
  - [01 Single Stack](../examples/01-quickstart-single-stack/README.md): Gateway, connector, and demo in one Compose file.
  - [02 Multi-Stack](../examples/02-multi-stack-external-net/README.md): Central gateway with separate application stacks.
  - [03 Docker Socket Proxy](../examples/03-secure-socket-proxy/README.md): Hardened setup isolating the Docker daemon socket.
  - [04 Advanced Labels & TLS](../examples/04-advanced-labels-tls-multiport/README.md): Custom headers, HTTPS origins, and multi-port containers.
  - [05 Multi-Account / Multi-Gateway](../examples/05-multi-account/README.md): Running multiple gateways with separate domains.

---

## ⚙️ Configuration & Networking

Comprehensive references for environment variables, container labels, and Docker networks:

- **[Environment Variables](configuration.md):** Complete variable reference, defaults, precedence, and optional features.
- **[Container Labels Reference](labels.md):** Hostname, port selection, origin TLS options, and metadata labels.
- **[Label Quick Reference](label-reference.md):** Compact cheat sheet of supported `cf.tunnel.*` labels.
- **[Docker Networking Guide](networking-guide.md):** How the shared bridge network routes traffic from `cloudflared` to application containers.

---

## 🛠️ Operations & Troubleshooting

Monitoring, maintenance, and day-2 operations:

- **[Operations Guide](operations.md):** Status checks, structured logs, Prometheus metrics (`/metrics`), and webhook alerts.
- **[Troubleshooting & FAQ](troubleshooting.md):** Diagnostic commands, DNS resolution checks, error codes, and common pitfalls.
- **[Compatibility & Upgrades](COMPATIBILITY.md):** Versioning guarantees, upgrade instructions, and rollback procedures.
- **[Release Security & Pinning](release-security.md):** Verifying image signatures, SLSA provenance, and digest pinning (ISS-03).

---

## 🔒 Security & Architecture

Deep dives into the internal mechanics and safety boundaries:

- **[Architecture & Safety Limits](architecture-and-safety.md):** Reconciliation loop, event debouncing, deletion limits, and [current limitations](architecture-and-safety.md#current-limitations).
- **[Security Model](security.md):** Threat model, Docker socket privileges, credential storage, and network isolation.
- **[Product Boundaries](product-boundaries.md):** Explicit list of what the project does and does NOT support.
- **[Support Matrix](support-matrix.md):** Supported Docker versions, Python runtimes, architectures, and Cloudflare features.
- **[HTTP API Reference](api.md):** Internal REST API endpoints (`/api/status`, `/api/health`, `/metrics`, `/api/sync`).
