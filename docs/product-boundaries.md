# Product Boundaries & Non-Goals (DOC-04)

This document establishes the architectural boundaries, core purpose, and explicit non-goals for `cf-docker-tunnel-sync`.

---

## 🎯 Core Purpose & Mission

`cf-docker-tunnel-sync` exists to **eliminate all manual friction when exposing Docker container services through Cloudflare Zero Trust Tunnels**.

It provides an automated, declarative synchronization engine that reads container lifecycle events and labels, manages Cloudflare Tunnel Ingress routing rules, and configures Cloudflare DNS CNAME records automatically with high availability and blast-radius safeguards.

---

## 🛡️ What the Project DOES

- ✅ **Automatic Service Discovery:** Listens to Docker socket lifecycle events (`start`, `die`, `restart`) and discovers containers marked with `cf.tunnel.*` labels.
- ✅ **Cloudflare Ingress Automation:** Dynamically updates Cloudflare Tunnel remote configuration rules to route traffic to running origin containers.
- ✅ **Cloudflare DNS Synchronization:** Automatically provisions and updates proxied CNAME records matching discovered container domains.
- ✅ **Graceful Deletion Safeguards:** Implements tombstoning grace periods and blast-radius circuit breakers to prevent accidental mass DNS deletion.
- ✅ **Preflight Diagnostics:** Evaluates Docker socket connectivity, token permissions, network topology, and origin health before mutations.
- ✅ **Decoupled Architecture:** Provides headless sync core and optional web dashboards (embedded or isolated companion Nginx container).

---

## 🚫 Explicit Non-Goals (What the Project Does NOT Do)

To maintain codebase simplicity, reliability, and security, the following capabilities are explicitly out of scope:

### 1. Not a General-Purpose LAN Reverse Proxy
- **Non-Goal:** Managing internal local area network (LAN) routing, self-signed TLS termination for internal clients, or replacing Nginx, Traefik, or Caddy for local traffic.
- **Rationale:** Cloudflare Zero Trust tunnels terminate TLS at Cloudflare's edge and route encrypted tunnel traffic over QUIC/HTTP2 to `cloudflared`. For local internal traffic bypasses, use dedicated LAN reverse proxies.

### 2. Not a Host Firewall or IPTables Manager
- **Non-Goal:** Manipulating host `iptables`, `nftables`, UFW, or Docker bridge packet filtering rules outside of Docker container network bindings.
- **Rationale:** Host security policies belong to system configuration management tools (Ansible, Puppet, NixOS, cloud-init).

### 3. Not a Multi-Cloud / Multi-DNS Provider Synchronizer
- **Non-Goal:** Synchronizing DNS records with AWS Route53, Google Cloud DNS, GoDaddy, Namecheap, or BIND.
- **Rationale:** The project is purpose-built and optimized exclusively for Cloudflare Zero Trust Tunnels and Cloudflare DNS.

### 4. Not an Orchestrator Ingress Controller (Kubernetes / Docker Swarm)
- **Non-Goal:** Operating as a Kubernetes Custom Resource Definition (CRD) Ingress Controller or Docker Swarm overlay routing mesh.
- **Rationale:** Specialized Cloudflare ingress controllers exist for Kubernetes. `cf-docker-tunnel-sync` is tailored specifically for Docker Compose and standalone Docker engines.

### 5. Not a Web Application Firewall (WAF) Rule Authoring Engine
- **Non-Goal:** Writing or maintaining Cloudflare WAF custom expression rules or Bot Management rules.
- **Rationale:** WAF rules are defined at the zone level in Cloudflare and are orthogonal to tunnel ingress routing.

---

## 📐 Roadmap Feature Acceptance Criteria

Every proposed feature, PR, or enhancement must satisfy this test:
> *"Does this feature directly reduce operational friction when running Docker services behind Cloudflare Tunnels without introducing breaking changes or bloating the core sync loop?"*
