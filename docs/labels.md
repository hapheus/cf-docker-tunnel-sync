# Docker Labels Reference

`cf-tunnel-sync` inspects container labels to dynamically manage Cloudflare Tunnel ingress rules and Cloudflare DNS CNAME records.

Only containers connected to the shared gateway network (`cf-tunnel-net`) and carrying `cf.tunnel.*` labels are routed.

---

## 🏷️ Supported Labels

| Label | Required | Aliases | Default | Description & Example |
| :--- | :--- | :--- | :--- | :--- |
| `cf.tunnel.hostname` | **Yes** | `cf.tunnel.domain`, `cf.tunnel.host` | — | The public Fully Qualified Domain Name (FQDN) for the service. Supports multiple comma-separated or space-separated hostnames.<br>`cf.tunnel.hostname=app.example.com`<br>`cf.tunnel.hostname=app.example.com,api.example.com` |
| `cf.tunnel.port` | Optional\* | `port` | auto-detected | The internal port the container listens on.<br>`cf.tunnel.port=8080`<br>\**Auto-detected if the image exposes exactly one port via `EXPOSE`.* |
| `cf.tunnel.proto` | Optional | `cf.tunnel.protocol`, `cf.tunnel.scheme` | `http` | Upstream protocol `cloudflared` uses to reach the container: `http`, `https`, `tcp`, `udp`, `ssh`, or `rdp`.<br>`cf.tunnel.proto=http` |
| `cf.tunnel.name` | Optional | `cf.tunnel.tunnel` | — | Scope container to a specific Cloudflare Tunnel. Ignored by other tunnels in multi-tunnel / multi-gateway environments.<br>`cf.tunnel.name=production-gateway` |
| `cf.tunnel.service` | Optional | — | auto-constructed | Explicit upstream service URL override (bypasses default `proto://container_name:port` resolution).<br>`cf.tunnel.service=http://custom-origin:8080` |
| `cf.tunnel.origin_request.no_tls_verify` | Optional | `cf.tunnel.notls_verify`, `cf.tunnel.notlsverify` | `false` | Disable TLS certificate verification between `cloudflared` and the origin container (essential for upstream services with self-signed SSL certs).<br>`cf.tunnel.origin_request.no_tls_verify=true` |
| `cf.tunnel.origin_request.origin_server_name` | Optional | `cf.tunnel.originServerName` | — | Custom SNI hostname to send in the TLS handshake to origin.<br>`cf.tunnel.origin_request.origin_server_name=app.local` |
| `cf.tunnel.origin_request.http_host_header` | Optional | `cf.tunnel.httpHostHeader` | — | Custom `Host` header sent to the upstream container origin.<br>`cf.tunnel.origin_request.http_host_header=app.internal` |
| `cf.tunnel.access_policy` | Optional | `cf.tunnel.access.policy` | — | Tag or identifier for Cloudflare Access integration policies.<br>`cf.tunnel.access_policy=internal-team` |

---

## 🎯 Port-Discovery Precedence & Two-Label Recommendation (DX-07)

`cf-tunnel-sync` resolves the upstream port using a deterministic precedence hierarchy:

```
1. Explicit Label:  cf.tunnel.port (or alias `port`)          --> HIGHEST PRECEDENCE
2. Image Metadata:  Single EXPOSE port in Dockerfile        --> Used if exactly 1 port exposed
3. Fallback:        Port 80 (with diagnostic warning logged) --> Used if 0 or >1 ports exposed
```

### ⚠️ Ambiguity with Multiple EXPOSE Ports
When an upstream image exposes multiple ports (e.g., `EXPOSE 80 443` or `EXPOSE 8080 9090`), automatic port discovery cannot guess which port serves HTTP traffic. Without an explicit label, `cf-tunnel-sync` falls back to port `80` and logs a preflight diagnostic warning.

### 🌟 The Golden Standard: The Explicit Two-Label Rule
To ensure 100% deterministic routing across image updates and multi-port containers, **always declare both labels**:

```yaml
labels:
  - "cf.tunnel.hostname=app.example.com"
  - "cf.tunnel.port=8080"
```

---

## 💡 Practical Examples

### 1. Minimal Web Application (HTTP)

```yaml
services:
  web:
    image: nginx:alpine
    networks:
      - cf-tunnel-net
    labels:
      - "cf.tunnel.hostname=web.example.com"
      - "cf.tunnel.port=80"

networks:
  cf-tunnel-net:
    external: true
```

### 2. Upstream HTTPS with Self-Signed Certificate

```yaml
services:
  vault:
    image: vaultwarden/server:latest
    networks:
      - cf-tunnel-net
    labels:
      - "cf.tunnel.hostname=vault.example.com"
      - "cf.tunnel.port=8443"
      - "cf.tunnel.proto=https"
      - "cf.tunnel.origin_request.no_tls_verify=true"

networks:
  cf-tunnel-net:
    external: true
```

### 3. Multi-Domain Routing to One Service

```yaml
services:
  api:
    image: my-api:latest
    networks:
      - cf-tunnel-net
    labels:
      - "cf.tunnel.hostname=api.example.com,core.example.com"
      - "cf.tunnel.port=3000"

networks:
  cf-tunnel-net:
    external: true
```
