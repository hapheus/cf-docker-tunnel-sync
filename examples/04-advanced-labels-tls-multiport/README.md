# ⚙️ Example 04: Advanced Ingress Labels, TLS & Multi-Port Routing

This example demonstrates how to configure advanced Cloudflare Tunnel ingress options for complex self-hosted backends (e.g. Nextcloud, Portainer, Proxmox, TrueNAS, MinIO).

---

## Scenarios Covered

### Scenario A: Internal Self-Signed HTTPS (`noTLSVerify`)
When a container originates HTTPS traffic internally with a self-signed certificate, Cloudflare will fail with SSL handshake errors unless origin verification is bypassed:

```yaml
labels:
  - "cf.tunnel.enable=true"
  - "cf.tunnel.hostname=tls-app.example.com"
  - "cf.tunnel.service=https://app-selfsigned-https:8443"
  - "cf.tunnel.originRequest.noTLSVerify=true"
```

### Scenario B: Custom `Host` Header & SNI (`originServerName`)
Some web applications (like Nextcloud or virtual-host reverse proxies) reject requests whose HTTP `Host` header does not match their internal hostname. Use these labels to rewrite the host header:

```yaml
labels:
  - "cf.tunnel.enable=true"
  - "cf.tunnel.hostname=cloud.example.com"
  - "cf.tunnel.port=80"
  - "cf.tunnel.originRequest.httpHostHeader=cloud.example.com"
  - "cf.tunnel.originRequest.originServerName=cloud.example.com"
```

### Scenario C: Disambiguating Containers with Multiple Exposed Ports
When a container image defines multiple `EXPOSE` directives (e.g. `80`, `443`, `8080`), `cf-tunnel-sync` issues a diagnostic warning and defaults to port 80. To explicitly route to a specific internal port, declare `cf.tunnel.port`:

```yaml
labels:
  - "cf.tunnel.enable=true"
  - "cf.tunnel.hostname=multiport.example.com"
  - "cf.tunnel.port=80"
```

---

## How to Run

1. Copy the environment file:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` with your API token and domain.
3. Start the services:
   ```bash
   docker compose up -d
   ```
