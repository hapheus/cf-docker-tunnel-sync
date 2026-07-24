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

Your Sync Dashboard is now available at `http://your-pi-ip:8090` (and will be exposed via tunnel at `https://tunnel-sync.${DOMAIN_NAME}`).

> ⚠️ **Dashboard Security & Basic Auth:** The dashboard is protected by Basic Authentication with default credentials `admin` / `admin`. You can change these inside your `.env` file (`BASIC_AUTH_USERNAME` and `BASIC_AUTH_PASSWORD`).
>
> While you can expose the dashboard publicly via the Cloudflare Tunnel (as shown in the default configuration), **it is highly recommended not to expose it to the public internet**. 
>
> To keep the dashboard private and only accessible inside your local home network, simply remove the `labels` section from the `cf-tunnel-sync` service in your `docker-compose.yml`:
> ```yaml
> # Remove these lines to disable public exposure:
> # labels:
> #   - "cf.tunnel.hostname=tunnel-sync.${DOMAIN_NAME}"
> #   - "cf.tunnel.port=8090"
> ```

---

## 🐳 Exposing Containers

Simply add the routing labels to any other container on the same network:

```yaml
services:
  my-web-app:
    image: nginx:alpine
    container_name: my-web-app
    labels:
      - "cf.tunnel.hostname=app.${DOMAIN_NAME}"
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
