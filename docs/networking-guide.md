# Docker Networking & Traffic Flow Guide

This document explains the network topology, packet flow from Cloudflare Edge to Docker containers, and best practices for eliminating `502 Bad Gateway` routing errors.

---

## 1. Control Plane vs. Data Plane Architecture

A fundamental design principle of `cf-docker-tunnel-sync` is the strict separation between the **Control Plane** and the **Data Plane**:

```mermaid
flowchart TD
    subgraph Cloudflare Global Anycast Edge
        Edge["Cloudflare Edge Anycast<br/>https://app.example.com"]
        API["Cloudflare API<br/>Zero Trust & DNS"]
    end

    subgraph Docker Host
        CFD["cloudflared<br/>(DATA PLANE DAEMON)"]
        Sync["cf-tunnel-sync<br/>(CONTROL PLANE CONTROLLER)"]
        App["Target Application Container<br/>(e.g., whoami, nextcloud)"]
    end

    Edge ===>|Encrypted QUIC / HTTP2 Tunnel (Outbound Port 7844)| CFD
    CFD -->|Internal Docker Bridge Network (cf-tunnel-net)| App
    Sync -->|1. Inspects Labels & Ports| App
    Sync -->|2. Configures Ingress & DNS| API
    Sync -.->|3. Writes Token File (/etc/cloudflared/token)| CFD
```

* **Control Plane (`cf-tunnel-sync`):**
  - Communicates with the Docker Engine and the Cloudflare REST API.
  - Computes the ChangePlan, updates remote ingress rules, synchronizes DNS CNAMEs, and writes the credentials token file.
  - **Does NOT proxy application traffic.**
* **Data Plane (`cloudflared`):**
  - Official Cloudflare daemon running alongside the sync controller.
  - Establishes encrypted outbound connections to Cloudflare's nearest edge data center.
  - Forwards incoming requests to your application containers across the private Docker bridge network.

---

## 2. Packet Flow: Step-by-Step

When an external user visits `https://app.example.com`:
1. The user's browser resolves `app.example.com` to Cloudflare's Edge Anycast IP addresses.
2. Cloudflare Edge routes the HTTP request across the existing Argo Tunnel established by your `cloudflared` container.
3. `cloudflared` receives the request inside the Docker host.
4. `cloudflared` queries Docker's internal embedded DNS server (`127.0.0.11`) to resolve the destination service name (e.g. `http://my-app:80`).
5. `cloudflared` sends the HTTP request directly to `my-app` across the shared bridge network (`cf-tunnel-net`).
6. The response flows back through `cloudflared` to Cloudflare Edge and the user.

---

## 3. Network Topologies

### Topology 1: Single-Stack (All-in-One Compose)
All services (`cloudflared`, `cf-tunnel-sync`, and app containers) are defined in one `docker-compose.yml` sharing an internal bridge network:
* See: [`examples/01-quickstart-single-stack/`](../examples/01-quickstart-single-stack/README.md)

### Topology 2: Decoupled Multi-Stack (External Network)
In real-world environments, services run in separate Compose stacks. To allow `cloudflared` to reach services in other stacks:
1. Create a dedicated external bridge network once:
   ```bash
   docker network create cf-tunnel-net
   ```
2. Attach `cloudflared` and `cf-tunnel-sync` to `cf-tunnel-net`.
3. In each independent application Compose file, attach the web-facing service to `cf-tunnel-net`:
   ```yaml
   services:
     web:
       image: my-service:latest
       networks:
         - default
         - cf-tunnel-net
       labels:
         - "cf.tunnel.enable=true"
         - "cf.tunnel.hostname=service.example.com"

   networks:
     cf-tunnel-net:
       external: true
   ```
* See: [`examples/02-multi-stack-external-net/`](../examples/02-multi-stack-external-net/README.md)

---

## 4. Why `502 Bad Gateway` Happens (and How to Fix It)

`HTTP 502 Bad Gateway` means Cloudflare Edge reached your `cloudflared` daemon, but `cloudflared` could not connect to your container.

| Root Cause | Technical Reason | Fix |
| :--- | :--- | :--- |
| **Missing Network Attachment** | Target container is not attached to `cf-tunnel-net`. | Add `cf-tunnel-net` to the container's `networks:` block. |
| **Listening on `127.0.0.1`** | Target service inside the container only binds to localhost loopback instead of `0.0.0.0`. | Configure application server (e.g. Uvicorn, Puma, Node) to bind to `0.0.0.0`. |
| **Port Mismatch** | `cf.tunnel.port` differs from the application's actual internal listening port. | Check actual container listening port and declare `cf.tunnel.port=<port>`. |
| **Self-Signed TLS Handshake Failure** | Origin service uses HTTPS with a self-signed cert, but `noTLSVerify` is not set. | Add label `cf.tunnel.originRequest.noTLSVerify=true`. |
