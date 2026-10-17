# Central Gateway Stack

This stack runs the `cloudflared` tunnel agent and the `cf-tunnel-sync` controller. It establishes the bridge network `cf-tunnel-net` that all other application stacks join.

---

## 🚀 How to Run

1. **Configure environment:**
   ```bash
   cp .env.example .env
   # Set DOMAIN_NAME and CLOUDFLARE_API_TOKEN
   ```

2. **Choose deployment mode:**

   ### Option A: Standard Gateway (with companion Web Dashboard)
   Starts `cloudflared`, `cf-tunnel-sync`, and `cf-tunnel-dashboard` (UI published on port 8080):
   ```bash
   docker compose up -d
   ```
   Access the dashboard at `http://<host-ip>:8080`.

   ### Option B: Canonical Headless Gateway (Zero Host-Published Ports)
   Starts only `cloudflared` and `cf-tunnel-sync` without any exposed host ports:
   ```bash
   docker compose -f docker-compose.headless.yml up -d
   ```

3. **Validate preflight:**
   ```bash
   docker compose run --rm cf-tunnel-sync --preflight
   ```

4. **Check status & logs:**
   - **CLI / Logs:** View background sync events via `docker compose logs -f cf-tunnel-sync`.
