# Example 01: All-In-One Single Compose Stack

This example demonstrates the simplest possible setup: running `cloudflared`, `cf-tunnel-sync`, the status dashboard, and your application container inside a **single `docker-compose.yml` file**.

---

## 🎯 When to Use This
- Quick testing or personal homelab setups on a single server.
- Projects where you prefer managing your tunnel and services together in one repository or directory.

---

## 🚀 How to Run

1. **Copy the environment template:**
   ```bash
   cp .env.example .env
   ```

2. **Configure `.env`:**
   Set your domain name, Cloudflare API token, and dashboard credentials:
   ```env
   DOMAIN_NAME=yourdomain.com
   CLOUDFLARE_API_TOKEN=your_token_here
   ```

3. **Start the stack:**
   ```bash
   docker compose up -d
   ```

4. **Verify:**
   - **Dashboard:** Open `http://<your-host-ip>:8080` in your browser.
   - **Service:** Within ~30 seconds, `cf-tunnel-sync` creates the tunnel, configures the ingress rules, and adds a proxied CNAME record for `app.<yourdomain.com>`. Access your application at `https://app.<yourdomain.com>`.
