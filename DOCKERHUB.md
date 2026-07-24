# Cloudflare Tunnel & Docker Sync

An automated tool to dynamically expose Docker containers using a **Cloudflare Zero Trust Tunnel** and manage DNS records automatically based on container labels.

This image scans your running Docker containers, automatically creates/configures a Cloudflare Tunnel, updates the ingress rules, and registers the required CNAME records on Cloudflare.

> ℹ️ **Domain Requirement:** Your domain must be **managed by Cloudflare** (meaning its DNS name servers point to Cloudflare). The domain does **not** need to be registered with Cloudflare Registrar (you can buy it anywhere else, like GoDaddy, Namecheap, etc.).

For full documentation, source code, and developer guides, visit the [GitHub Repository](https://github.com/hapheus/cf-docker-tunnel-sync).

---

## 🛠️ Quick Start

Create a `docker-compose.yml` file:

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    restart: always
    command: tunnel --no-autoupdate run --token-file /etc/cloudflared/token
    volumes:
      - cf_token_data:/etc/cloudflared
    networks:
      - cf-tunnel-net
    extra_hosts:
      - "host.docker.internal:host-gateway"

  cf-tunnel-sync:
    image: hapheus/cf-tunnel-sync:latest
    container_name: cf-tunnel-sync
    restart: always
    environment:
      - CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}
      - DOMAIN_NAME=${DOMAIN_NAME}
      - CLOUDFLARE_TUNNEL_NAME=${CLOUDFLARE_TUNNEL_NAME:-cf-docker-tunnel-sync}
      - POLL_INTERVAL=30
      - BASIC_AUTH_USERNAME=${BASIC_AUTH_USERNAME:-admin}
      - BASIC_AUTH_PASSWORD=${BASIC_AUTH_PASSWORD:-admin}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - cf_token_data:/etc/cloudflared
    labels:
      - "cf.tunnel.hostname=tunnel-sync.${DOMAIN_NAME}"
      - "cf.tunnel.port=8090"
    ports:
      - "8090:8090"
    networks:
      - cf-tunnel-net

networks:
  cf-tunnel-net:
    driver: bridge

volumes:
  cf_token_data:
```

### Configure `.env`
```env
DOMAIN_NAME=yourdomain.com
CLOUDFLARE_API_TOKEN=your_cloudflare_api_token_here
CLOUDFLARE_TUNNEL_NAME=cf-docker-tunnel-sync
```

Start the stack:
```bash
docker compose up -d
```

---

## 🐳 Exposing Containers

Simply add the routing labels to any other container on the same network:

```yaml
services:
  my-web-app:
    image: nginx:alpine
    container_name: my-web-app
    labels:
      - "cf.tunnel.hostname=app.yourdomain.com"
      - "cf.tunnel.port=80"
    networks:
      - cf-tunnel-net
```

---

## 💝 Support the Project

If you find this project helpful, consider showing some support:

- ☕ **Buy me a coffee:** Send a tip via [PayPal](http://paypal.me/hapheus).
- 🎗️ **Charity Donation:** Donate to [Österreichische Krebshilfe (Austrian Cancer Aid)](https://www.krebshilfe.net/) or any local animal welfare organization.
- 🎯 **Dream Support:** I would love some tickets for the World Darts Championship at **Ally Pally** (Alexandra Palace) 😅 – hopefully, I will make it there one day!
